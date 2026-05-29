from core.instruction_renderer.renderer import InstructionBlock, renderer


def _render(ctx: dict) -> str:
    user_id = ctx["user_id"]
    session_id = ctx["session_id"]
    upload_dir = ctx["upload_dir"]
    return f"""            VISION SUPPORT:
            -- You can view images directly.
            -- If the user submits a filepath, you will also see the image. The filepath and user image will both be in the user's message.
            -- To display a matplotlib plot, use this EXACT 3-line pattern every time, no exceptions:
               out = '/app/static/{user_id}/{session_id}/uploads/FILENAME.png'
               plt.savefig(out, dpi=150, bbox_inches='tight'); plt.close()
               from IPython.display import Image as IPImage; display(IPImage(out))
            -- The display(IPImage(out)) line is MANDATORY — without it the image is invisible to the user.
            -- Do NOT call plt.show() — it causes FileNotFoundError in this environment.
            -- DO NOT perform OCR or any separate text-extraction step on images. Use your vision to read text directly."""


renderer.register(InstructionBlock(
    name="output_format",
    tags=frozenset({"output"}),
    render=_render,
))
