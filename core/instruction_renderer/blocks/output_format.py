from core.instruction_renderer.renderer import InstructionBlock, renderer


def _render(ctx: dict) -> str:
    user_id = ctx["user_id"]
    session_id = ctx["session_id"]
    upload_dir = ctx["upload_dir"]
    return f"""            VISION SUPPORT:
            -- You can view images directly.
            -- If the user submits a filepath, you will also see the image. The filepath and user image will both be in the user's message.
            -- If you use `plt.show()`, the resulting image will be sent to you.
            -- For plots created with matplotlib, display them exactly once with `plt.show()`. Do not call `PIL.Image.show()` on the saved plot file.
            -- DO NOT perform OCR or any separate text-extraction step on images. Use your vision to read text directly.
            image_path = '/app/static/{user_id}/{session_id}/FILENAME' OR image_path = '/app/static/{user_id}/{session_id}/{upload_dir}/FILENAME'
            image = Image.open(image_path)
            image.show()"""


renderer.register(InstructionBlock(
    name="output_format",
    tags=frozenset({"output"}),
    render=_render,
))
