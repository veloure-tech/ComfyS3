import importlib
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class FakeNumericArray:
    def __rmul__(self, _other):
        return self

    def astype(self, _dtype):
        return self

    def __truediv__(self, _other):
        return self


class FakeTensor:
    def __getitem__(self, _item):
        return self

    def __rsub__(self, _other):
        return self

    def unsqueeze(self, _dim):
        return self


class FakeInputImage:
    def cpu(self):
        return self

    def numpy(self):
        return FakeNumericArray()


class FakeFrame:
    mode = "RGB"

    def point(self, _fn):
        return self

    def convert(self, _mode):
        return self

    def getbands(self):
        return ("R", "G", "B")


def reset_repo_modules():
    for module_name in [
        "src.client_s3",
        "src.nodes.load_image_s3",
        "src.nodes.save_image_s3",
    ]:
        sys.modules.pop(module_name, None)


def install_stub_modules(saved_calls=None, opened_paths=None):
    if saved_calls is None:
        saved_calls = []
    if opened_paths is None:
        opened_paths = []

    os.environ.setdefault("S3_REGION", "region")
    os.environ.setdefault("S3_ACCESS_KEY", "access")
    os.environ.setdefault("S3_SECRET_KEY", "secret")
    os.environ.setdefault("S3_BUCKET_NAME", "bucket")

    boto3_module = types.ModuleType("boto3")
    boto3_module.resource = mock.Mock(return_value=types.SimpleNamespace())

    botocore_module = types.ModuleType("botocore")
    botocore_module.__path__ = []
    botocore_config_module = types.ModuleType("botocore.config")
    botocore_config_module.Config = lambda **kwargs: kwargs
    botocore_exceptions_module = types.ModuleType("botocore.exceptions")

    class NoCredentialsError(Exception):
        pass

    botocore_exceptions_module.NoCredentialsError = NoCredentialsError

    dotenv_module = types.ModuleType("dotenv")
    dotenv_module.load_dotenv = lambda: None

    numpy_module = types.ModuleType("numpy")
    numpy_module.array = lambda _value: FakeNumericArray()
    numpy_module.clip = lambda value, _min_value, _max_value: value
    numpy_module.float32 = "float32"
    numpy_module.uint8 = "uint8"

    torch_module = types.ModuleType("torch")
    torch_module.float32 = "float32"
    torch_module.from_numpy = lambda _value: FakeTensor()
    torch_module.zeros = lambda *_args, **_kwargs: FakeTensor()
    torch_module.cat = lambda values, dim=0: ("cat", values, dim)

    pil_module = types.ModuleType("PIL")
    pil_module.__path__ = []
    pil_image_module = types.ModuleType("PIL.Image")
    pil_image_ops_module = types.ModuleType("PIL.ImageOps")
    pil_image_sequence_module = types.ModuleType("PIL.ImageSequence")
    pil_png_image_plugin_module = types.ModuleType("PIL.PngImagePlugin")

    class FakePngInfo:
        def __init__(self):
            self.text = []

        def add_text(self, key, value):
            self.text.append((key, value))

    class FakeSavedImage:
        def save(self, path, pnginfo=None, compress_level=None):
            saved_calls.append(
                {
                    "path": path,
                    "pnginfo": pnginfo,
                    "compress_level": compress_level,
                }
            )
            with open(path, "wb") as file_handle:
                file_handle.write(b"png")

    pil_image_module.open = lambda path: opened_paths.append(path) or object()
    pil_image_module.fromarray = lambda _value: FakeSavedImage()
    pil_image_ops_module.exif_transpose = lambda image: image
    pil_image_sequence_module.Iterator = lambda _image: [FakeFrame()]
    pil_png_image_plugin_module.PngInfo = FakePngInfo

    comfy_module = types.ModuleType("comfy")
    comfy_module.__path__ = []
    comfy_cli_args_module = types.ModuleType("comfy.cli_args")
    comfy_cli_args_module.args = types.SimpleNamespace(disable_metadata=False)

    sys.modules["boto3"] = boto3_module
    sys.modules["botocore"] = botocore_module
    sys.modules["botocore.config"] = botocore_config_module
    sys.modules["botocore.exceptions"] = botocore_exceptions_module
    sys.modules["dotenv"] = dotenv_module
    sys.modules["numpy"] = numpy_module
    sys.modules["torch"] = torch_module
    sys.modules["PIL"] = pil_module
    sys.modules["PIL.Image"] = pil_image_module
    sys.modules["PIL.ImageOps"] = pil_image_ops_module
    sys.modules["PIL.ImageSequence"] = pil_image_sequence_module
    sys.modules["PIL.PngImagePlugin"] = pil_png_image_plugin_module
    sys.modules["comfy"] = comfy_module
    sys.modules["comfy.cli_args"] = comfy_cli_args_module


class SaveImageS3Tests(unittest.TestCase):
    def setUp(self):
        reset_repo_modules()
        self.saved_calls = []
        install_stub_modules(saved_calls=self.saved_calls)

    def test_save_images_uses_exact_s3_key_and_content_type(self):
        module = importlib.import_module("src.nodes.save_image_s3")
        upload_calls = []

        def fake_upload_file(local_path, s3_path, extra_args=None):
            upload_calls.append(
                {
                    "local_path": local_path,
                    "s3_path": s3_path,
                    "extra_args": extra_args,
                }
            )
            return s3_path

        module.S3_INSTANCE = types.SimpleNamespace(
            upload_file=fake_upload_file,
            get_save_path=mock.Mock(side_effect=AssertionError("get_save_path should not be used")),
        )

        node = module.SaveImageS3()
        result = node.save_images(
            [FakeInputImage()],
            filename_prefix="flat-uuid-key",
            prompt={"workflow": "demo"},
            extra_pnginfo={"seed": 123},
        )

        self.assertEqual(len(upload_calls), 1)
        self.assertEqual(upload_calls[0]["s3_path"], "flat-uuid-key")
        self.assertEqual(upload_calls[0]["extra_args"], {"ContentType": "image/png"})
        self.assertFalse(os.path.exists(upload_calls[0]["local_path"]))
        self.assertEqual(result["result"], (["flat-uuid-key"],))
        self.assertEqual(result["ui"]["images"][0]["filename"], "flat-uuid-key")
        self.assertEqual(result["ui"]["images"][0]["subfolder"], "")
        self.assertEqual(self.saved_calls[0]["compress_level"], 4)
        self.assertIn(("prompt", '{"workflow": "demo"}'), self.saved_calls[0]["pnginfo"].text)
        self.assertIn(("seed", "123"), self.saved_calls[0]["pnginfo"].text)

    def test_save_images_overwrites_same_exact_key_for_batches(self):
        module = importlib.import_module("src.nodes.save_image_s3")
        upload_calls = []

        def fake_upload_file(local_path, s3_path, extra_args=None):
            upload_calls.append((local_path, s3_path, extra_args))
            return s3_path

        module.S3_INSTANCE = types.SimpleNamespace(upload_file=fake_upload_file)

        node = module.SaveImageS3()
        result = node.save_images(
            [FakeInputImage(), FakeInputImage()],
            filename_prefix="flat-uuid-key",
        )

        self.assertEqual(len(upload_calls), 2)
        self.assertTrue(all(call[1] == "flat-uuid-key" for call in upload_calls))
        self.assertEqual(result["result"], (["flat-uuid-key", "flat-uuid-key"],))


class LoadImageS3Tests(unittest.TestCase):
    def setUp(self):
        reset_repo_modules()
        self.opened_paths = []
        install_stub_modules(opened_paths=self.opened_paths)

    def test_load_image_uses_exact_s3_key_and_temp_download(self):
        module = importlib.import_module("src.nodes.load_image_s3")
        download_calls = []

        def fake_download_file(s3_path, local_path):
            download_calls.append((s3_path, local_path))
            return local_path

        module.S3_INSTANCE = types.SimpleNamespace(
            download_file=fake_download_file,
            get_files=mock.Mock(side_effect=AssertionError("get_files should not be used")),
        )

        node = module.LoadImageS3()
        output_image, output_mask = node.load_image("flat-uuid-key")

        self.assertEqual(download_calls[0][0], "flat-uuid-key")
        self.assertEqual(self.opened_paths[0], download_calls[0][1])
        self.assertFalse(os.path.exists(download_calls[0][1]))
        self.assertIsInstance(output_image, FakeTensor)
        self.assertIsInstance(output_mask, FakeTensor)

    def test_load_input_type_is_string(self):
        module = importlib.import_module("src.nodes.load_image_s3")
        input_type = module.LoadImageS3.INPUT_TYPES()["required"]["image"]
        self.assertEqual(input_type[0], "STRING")


class ClientS3Tests(unittest.TestCase):
    def setUp(self):
        reset_repo_modules()
        install_stub_modules()

    def test_upload_file_forwards_extra_args(self):
        module = importlib.import_module("src.client_s3")
        fake_bucket = mock.Mock()
        fake_client = mock.Mock()
        fake_client.Bucket.return_value = fake_bucket

        s3_instance = module.S3.__new__(module.S3)
        s3_instance.s3_client = fake_client
        s3_instance.bucket_name = "bucket"

        result = module.S3.upload_file(
            s3_instance,
            "local.png",
            "flat-uuid-key",
            extra_args={"ContentType": "image/png"},
        )

        self.assertEqual(result, "flat-uuid-key")
        fake_bucket.upload_file.assert_called_once_with(
            "local.png",
            "flat-uuid-key",
            ExtraArgs={"ContentType": "image/png"},
        )

    def test_init_does_not_require_input_or_output_dirs(self):
        module = importlib.import_module("src.client_s3")

        with mock.patch.dict(
            os.environ,
            {
                "S3_REGION": "region",
                "S3_ACCESS_KEY": "access",
                "S3_SECRET_KEY": "secret",
                "S3_BUCKET_NAME": "bucket",
            },
            clear=False,
        ):
            os.environ.pop("S3_INPUT_DIR", None)
            os.environ.pop("S3_OUTPUT_DIR", None)

            with mock.patch.object(module.S3, "get_client", return_value=object()):
                with mock.patch.object(module.S3, "does_folder_exist") as does_folder_exist:
                    with mock.patch.object(module.S3, "create_folder") as create_folder:
                        module.S3("region", "access", "secret", "bucket", None)

        does_folder_exist.assert_not_called()
        create_folder.assert_not_called()


if __name__ == "__main__":
    unittest.main()
