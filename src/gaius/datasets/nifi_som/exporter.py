"""Export dataset in Magma/LLaVA-compatible conversation format."""

import json
from pathlib import Path
from datetime import datetime
from typing import Union

from .models import DatasetExample, TraceExample


class MagmaExporter:
    """Export dataset examples to Magma/LLaVA conversation format.

    Output format is compatible with:
    - Magma-8B finetuning
    - LLaVA-1.5 finetuning
    - Other LLaVA-family models

    Each example follows the structure:
    {
        "id": "unique_id",
        "image": "path/to/image.png",
        "conversations": [
            {"from": "human", "value": "<image>\n{instruction}"},
            {"from": "gpt", "value": "{response}"}
        ]
    }
    """

    def __init__(
        self,
        output_dir: Path,
        storage_backend: str = "minio",
        dataset_id: str = "nifi-som-v1",
        dataset_version: str = "1.0.0",
    ):
        self.output_dir = Path(output_dir)
        self.images_dir = self.output_dir / "images"
        self.storage_backend = storage_backend
        self.dataset_id = dataset_id
        self.dataset_version = dataset_version

    def export(
        self, examples: list[Union[DatasetExample, TraceExample]]
    ) -> Path:
        """Export all examples to the output directory or S3.

        Args:
            examples: List of dataset examples (SoM or ToM) to export

        Returns:
            Path to the output file (annotations.json or manifest.json)
        """
        if self.storage_backend == "minio":
            return self._export_to_s3(examples)
        else:
            return self._export_to_filesystem(examples)

    def _export_to_filesystem(
        self, examples: list[Union[DatasetExample, TraceExample]]
    ) -> Path:
        """Export to local filesystem in Magma format."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)

        annotations = []

        for example in examples:
            if isinstance(example, TraceExample):
                # ToM: save multiple frames
                frame_paths = []
                for i, frame in enumerate(example.frames):
                    frame_filename = f"{example.id}_frame_{i:02d}.png"
                    frame_path = self.images_dir / frame_filename
                    frame.save(frame_path, "PNG")
                    frame_paths.append(f"images/{frame_filename}")

                annotation = example.to_magma_format(frame_paths)
            else:
                # SoM: single image
                img_filename = f"{example.id}.png"
                img_path = self.images_dir / img_filename
                example.image.save(img_path, "PNG")
                annotation = example.to_magma_format(f"images/{img_filename}")

            annotations.append(annotation)

        # Write annotations JSON (Magma format)
        annotations_path = self.output_dir / "annotations.json"
        with open(annotations_path, "w") as f:
            json.dump(annotations, f, indent=2)

        self._update_generation_log(len(examples), "filesystem")
        return annotations_path

    def _export_to_s3(
        self, examples: list[Union[DatasetExample, TraceExample]]
    ) -> Path:
        """Export to S3/MinIO with manifest in KB."""
        from ..storage import DatasetStorage

        storage = DatasetStorage(backend="minio")

        annotations = []
        image_infos = []
        total_frames = 0

        for example in examples:
            if isinstance(example, TraceExample):
                # ToM: upload multiple frames
                frame_paths = []
                for i, frame in enumerate(example.frames):
                    frame_filename = f"images/{example.id}_frame_{i:02d}.png"
                    info = storage.upload_image(
                        self.dataset_id, frame_filename, frame
                    )
                    image_infos.append(info)
                    frame_paths.append(frame_filename)
                    total_frames += 1

                annotation = example.to_magma_format(frame_paths)
            else:
                # SoM: single image
                img_path = f"images/{example.id}.png"
                info = storage.upload_image(
                    self.dataset_id, img_path, example.image
                )
                image_infos.append(info)
                annotation = example.to_magma_format(img_path)

            annotations.append(annotation)

        # Upload annotations.json to S3
        annotations_info = storage.upload_json(
            self.dataset_id, "annotations.json", annotations
        )

        # Compute stats
        som_examples = [a for a in annotations if not a.get("_metadata", {}).get("mode") == "tom"]
        tom_examples = [a for a in annotations if a.get("_metadata", {}).get("mode") == "tom"]
        marks_per_example = [
            len(a.get("_metadata", {}).get("som_marks", []))
            for a in annotations
        ]
        stats = {
            "total_examples": len(examples),
            "som_examples": len(som_examples),
            "tom_examples": len(tom_examples),
            "total_frames": total_frames if total_frames else len(image_infos),
            "avg_marks_per_example": (
                sum(marks_per_example) / len(marks_per_example)
                if marks_per_example
                else 0
            ),
            "format": "magma",
            "format_version": "1.0",
        }

        # Create and write manifest to KB
        manifest = storage.create_manifest(
            dataset_id=self.dataset_id,
            version=self.dataset_version,
            annotations_info=annotations_info,
            image_infos=image_infos,
            stats=stats,
        )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = storage.write_manifest_to_kb(manifest, self.output_dir)

        self._update_generation_log(len(examples), "minio")
        return manifest_path

    def _update_generation_log(self, num_examples: int, backend: str = "filesystem"):
        """Update the generation log with this run."""
        log_path = self.output_dir / "generation-log.md"

        timestamp = datetime.now().isoformat()
        entry = f"\n## Run: {timestamp}\n\n"
        entry += f"- Examples generated: {num_examples}\n"
        entry += f"- Storage backend: {backend}\n"
        entry += f"- Format: Magma/LLaVA conversation\n"
        entry += f"- Output: {self.output_dir}\n"

        if log_path.exists():
            with open(log_path, "a") as f:
                f.write(entry)
        else:
            with open(log_path, "w") as f:
                f.write("# NiFi-SoM Generation Log\n")
                f.write(entry)

    def export_single(self, example: DatasetExample) -> dict:
        """Export a single example and return its annotation.

        Args:
            example: Dataset example to export

        Returns:
            Annotation dictionary in Magma format
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)

        img_filename = f"{example.id}.png"
        img_path = self.images_dir / img_filename
        example.image.save(img_path, "PNG")

        return example.to_magma_format(f"images/{img_filename}")

    def load_annotations(self) -> list[dict]:
        """Load existing annotations from the output directory.

        Returns:
            List of annotation dictionaries
        """
        annotations_path = self.output_dir / "annotations.json"
        if annotations_path.exists():
            with open(annotations_path) as f:
                return json.load(f)
        return []

    def append_examples(self, examples: list[DatasetExample]) -> Path:
        """Append new examples to existing annotations.

        Args:
            examples: New examples to add

        Returns:
            Path to the updated annotations.json
        """
        annotations = self.load_annotations()

        for example in examples:
            annotation = self.export_single(example)
            annotations.append(annotation)

        annotations_path = self.output_dir / "annotations.json"
        with open(annotations_path, "w") as f:
            json.dump(annotations, f, indent=2)

        self._update_generation_log(len(examples))
        return annotations_path


def validate_magma_format(annotations_path: Path) -> dict:
    """Validate a Magma-format annotations file.

    Checks that the file follows the LLaVA/Magma conversation format:
    - Each entry has 'id', 'image', 'conversations'
    - Conversations alternate human/gpt
    - Human messages contain '<image>' token

    Args:
        annotations_path: Path to annotations.json

    Returns:
        Validation result with any errors found
    """
    result = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "stats": {},
    }

    try:
        with open(annotations_path) as f:
            annotations = json.load(f)
    except json.JSONDecodeError as e:
        result["valid"] = False
        result["errors"].append(f"Invalid JSON: {e}")
        return result

    if not isinstance(annotations, list):
        result["valid"] = False
        result["errors"].append("Annotations must be a list")
        return result

    result["stats"]["total_examples"] = len(annotations)
    images_dir = annotations_path.parent / "images"

    for i, ann in enumerate(annotations):
        # Check required Magma fields
        if "id" not in ann:
            result["errors"].append(f"Example {i}: missing 'id'")
            result["valid"] = False

        if "image" not in ann:
            result["errors"].append(f"Example {i}: missing 'image'")
            result["valid"] = False

        if "conversations" not in ann:
            result["errors"].append(f"Example {i}: missing 'conversations'")
            result["valid"] = False
            continue

        convs = ann["conversations"]
        if not isinstance(convs, list) or len(convs) < 2:
            result["errors"].append(f"Example {i}: conversations must have at least 2 turns")
            result["valid"] = False
            continue

        # Check conversation structure
        if convs[0].get("from") != "human":
            result["warnings"].append(f"Example {i}: first turn should be from 'human'")

        if convs[1].get("from") != "gpt":
            result["warnings"].append(f"Example {i}: second turn should be from 'gpt'")

        # Check for image token
        human_value = convs[0].get("value", "")
        if "<image>" not in human_value:
            result["warnings"].append(f"Example {i}: human message missing '<image>' token")

        # Check image exists
        if "image" in ann:
            img_path = annotations_path.parent / ann["image"]
            if not img_path.exists():
                result["warnings"].append(f"Example {i}: image not found: {ann['image']}")

        # Count marks if metadata present
        if "_metadata" in ann and "som_marks" in ann["_metadata"]:
            marks = ann["_metadata"]["som_marks"]
            result["stats"].setdefault("marks_per_example", []).append(len(marks))

    if "marks_per_example" in result["stats"]:
        marks = result["stats"]["marks_per_example"]
        result["stats"]["avg_marks"] = sum(marks) / len(marks) if marks else 0

    return result
