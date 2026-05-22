from core.tool_registry.registry import Tool, registry

_code = '''# In-memory Docs cache keyed by user_id -> {"docs": Docs, "revision": str}
# Revision is derived from the set of indexed file names so it auto-invalidates
# when papers are uploaded or deleted.
_docs_cache = {}

def query_knowledge_base(query, user_id, session_id=None):
    """Query the user\'s Knowledge base using PaperQA.

    This function uses the persistent index approach to query papers in the user\'s
    Knowledge base. It preserves media content for future extraction.

    Parameters:
        query (str): The question to ask about the papers.
        user_id (str): The user\'s ID to load their specific paper directory.
        session_id (str, optional): Session ID for saving images to the correct directory.

    Returns:
        dict: A dictionary containing:
            - answer (str): The formatted answer with references
            - images (list): List of dicts with image info (path, page, description, url)
    """
    import asyncio
    import nest_asyncio
    import base64
    import hashlib
    from pathlib import Path
    from paperqa import Docs
    from paperqa.agents.search import get_directory_index
    from core.rag_store import get_user_settings

    # Apply nest_asyncio to allow nested event loops (needed when running from Open Interpreter)
    nest_asyncio.apply()

    def save_base64_image(data_url, output_dir, prefix="kb_figure"):
        """Save a base64 data URL to an image file.

        Returns the saved file path or None if failed.
        """
        try:
            # Parse the data URL: data:image/png;base64,XXXXX
            if not data_url or not data_url.startswith("data:image"):
                return None

            # Extract mime type and base64 data
            header, b64_data = data_url.split(",", 1)
            mime_type = header.split(":")[1].split(";")[0]  # e.g., "image/png"

            # Determine file extension
            ext_map = {
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/jpg": ".jpg",
                "image/gif": ".gif",
                "image/webp": ".webp",
            }
            ext = ext_map.get(mime_type, ".png")

            # Create a unique filename based on content hash
            content_hash = hashlib.md5(b64_data.encode()).hexdigest()[:12]
            filename = f"{prefix}_{content_hash}{ext}"
            filepath = output_dir / filename

            # Skip if file already exists (deduplication)
            if filepath.exists():
                return filepath

            # Decode and save
            image_data = base64.b64decode(b64_data)
            output_dir.mkdir(parents=True, exist_ok=True)
            filepath.write_bytes(image_data)

            return filepath
        except Exception as e:
            print(f"[PQA] Warning: Failed to save image: {e}")
            return None

    async def _query_async():
        global _docs_cache
        t_start = _time.perf_counter()

        print("[PQA] Step 1: Loading user settings...")
        # Step 1: Get user-specific settings
        settings = get_user_settings(user_id)
        print(f"[PQA] Settings loaded. LLM: {settings.llm}, Embedding: {settings.embedding}")

        print("[PQA] Step 2: Building/loading index...")
        # Step 2: Build/reuse the persistent index
        t_idx = _time.perf_counter()
        index = await get_directory_index(settings=settings)
        print(f"[PQA] Index loaded in {_time.perf_counter() - t_idx:.2f}s.")

        # Check if there are any indexed files
        index_files = await index.index_files
        if not index_files:
            return {"answer": "No papers found in your Knowledge base. Please upload papers first.", "images": []}
        print(f"[PQA] Found {len(index_files)} indexed files.")

        # Compute a revision fingerprint from the set of indexed file names
        revision = hashlib.md5(str(sorted(index_files.keys())).encode()).hexdigest()
        cache_key = str(user_id)
        cached = _docs_cache.get(cache_key)

        if cached and cached["revision"] == revision:
            # Fast path: in-memory cache from a previous query in this session
            docs = cached["docs"]
            print("[PQA] Step 3: Reusing cached Docs object (in-memory cache hit).")
        else:
            # Try disk-based cache (pre-built during background index build)
            from core.rag_store import load_docs_from_disk, save_docs_to_disk
            disk_docs = load_docs_from_disk(user_id, revision)

            if disk_docs is not None:
                docs = disk_docs
                _docs_cache[cache_key] = {"docs": docs, "revision": revision}
                print("[PQA] Step 3: Loaded Docs from disk cache (pre-built during upload/delete or prior lazy backfill).")
            else:
                # Full rebuild: parse + embed all papers and lazily backfill disk cache
                print("[PQA] Step 3: Building Docs object (no cache available; query-time lazy backfill)...")
                t_docs = _time.perf_counter()
                docs = Docs()
                paper_directory = settings.agent.index.paper_directory

                for file_path in index_files.keys():
                    full_path = paper_directory / file_path
                    if full_path.exists():
                        print(f"[PQA]   Adding: {file_path}")
                        await docs.aadd(full_path, settings=settings)

                # Cache the built Docs object for future queries
                _docs_cache[cache_key] = {"docs": docs, "revision": revision}
                save_docs_to_disk(user_id, docs, revision)
                print(f"[PQA] Docs built and cached in {_time.perf_counter() - t_docs:.2f}s.")

        # Step 4: Query with docs.aquery() - preserves media content
        print(f"[PQA] Step 4: Querying with: \'{query}\'...")
        t_query = _time.perf_counter()
        session = await docs.aquery(query=query, settings=settings)
        print(f"[PQA] Query complete in {_time.perf_counter() - t_query:.2f}s.")

        # Step 5: Extract and save images from contexts
        print("[PQA] Step 5: Extracting images from contexts...")

        # Determine output directory for images
        static_dir = Path("static")
        if session_id:
            output_dir = static_dir / str(user_id) / session_id / "pqa_media"
        else:
            output_dir = static_dir / str(user_id) / "pqa_media"

        saved_images = []
        seen_hashes = set()  # For deduplication across contexts

        # Get contexts that were actually used in the answer
        used_context_ids = getattr(session, "used_contexts", set())

        for context in session.contexts:
            # Prioritize used contexts but also include others with media
            is_used = context.id in used_context_ids if used_context_ids else True

            if not hasattr(context, "text") or not hasattr(context.text, "media"):
                continue

            for media in context.text.media:
                try:
                    data_url = media.to_image_url()
                    if not data_url:
                        continue

                    # Check for duplicates using content hash
                    if "," in data_url:
                        b64_part = data_url.split(",", 1)[1]
                        content_hash = hashlib.md5(b64_part.encode()).hexdigest()
                        if content_hash in seen_hashes:
                            continue
                        seen_hashes.add(content_hash)

                    # Save the image
                    saved_path = save_base64_image(data_url, output_dir)
                    if saved_path:
                        # Get metadata from media info
                        info = getattr(media, "info", {}) or {}
                        page_num = info.get("page_num", info.get("page"))
                        media_type = info.get("type", "image")
                        description = info.get("enriched_description", "")

                        # Build relative URL for frontend
                        rel_path = saved_path.relative_to(static_dir)

                        saved_images.append({
                            "path": str(saved_path),
                            "relative_path": str(rel_path),
                            "page": page_num,
                            "type": media_type,
                            "description": description,
                            "context_id": context.id,
                            "used_in_answer": is_used,
                            "chunk_name": getattr(context.text, "name", ""),
                        })
                        print(f"[PQA] Saved: {saved_path.name} (page {page_num})")
                except Exception as e:
                    print(f"[PQA] Warning: Failed to process media: {e}")
                    continue

        print(f"[PQA] Extracted {len(saved_images)} unique images.")
        print(f"[PQA] Total query_knowledge_base time: {_time.perf_counter() - t_start:.2f}s")

        # Return structured result
        return {
            "answer": str(session),
            "images": saved_images,
        }

    # With nest_asyncio applied, we can safely use asyncio.run() or get_event_loop()
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(_query_async())'''

registry.register(Tool(name="rag_tools", tags=frozenset({"rag"}), code=_code))
