import os
import tempfile
import numpy as np
from PIL import Image

from ..client_s3 import get_s3_instance
S3_INSTANCE = get_s3_instance()


class SaveImageS3:
    def __init__(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
        self.temp_dir = os.path.join(base_dir, "temp/")
        self.s3_output_dir = os.getenv("S3_OUTPUT_DIR")
        self.type = "output"
        self.prefix_append = ""
        self.compress_level = 4

    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "images": ("IMAGE", ),
            "filename_prefix": ("STRING", {"default": "Image"})},
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"
            },
                }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("s3_image_paths",)
    FUNCTION = "save_images"
    OUTPUT_NODE = True
    OUTPUT_IS_LIST = (True,)
    CATEGORY = "ComfyS3"

    def save_images(self, images, filename_prefix, prompt=None, extra_pnginfo=None):
        if not filename_prefix:
            raise ValueError("SaveImageS3 requires an exact S3 key.")

        results = list()
        s3_image_paths = list()
        filename = os.path.basename(filename_prefix)
        subfolder = os.path.dirname(filename_prefix)
        
        for image in images:
            i = 255. * image.cpu().numpy()
            img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))
            
            temp_file_path = None
            try:
                # Create a temporary file
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_file:
                    temp_file_path = temp_file.name
                    
                    # Save the image to the temporary file
                    img.save(temp_file_path, compress_level=self.compress_level)

                    # Upload the temporary file to S3
                    file_path = S3_INSTANCE.upload_file(
                        temp_file_path,
                        filename_prefix,
                        extra_args={"ContentType": "image/png"},
                    )

                    # Add the s3 path to the s3_image_paths list
                    s3_image_paths.append(file_path)
                    
                    # Add the result to the results list
                    results.append({
                        "filename": filename,
                        "subfolder": subfolder,
                        "type": self.type
                    })

            finally:
                # Delete the temporary file
                if temp_file_path and os.path.exists(temp_file_path):
                    os.remove(temp_file_path)

        return { "ui": { "images": results },  "result": (s3_image_paths,) }
