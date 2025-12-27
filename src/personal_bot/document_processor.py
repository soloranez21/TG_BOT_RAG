"""
Document Processor - handles ZIP extraction and document parsing.
"""
import zipfile
import tempfile
import logging
from pathlib import Path
from typing import Generator

from langchain_community.document_loaders import (
    PyPDFLoader,
    Docx2txtLoader,
    TextLoader,
    UnstructuredHTMLLoader,
    UnstructuredPowerPointLoader,
)
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

logger = logging.getLogger(__name__)

# Mapping of file extensions to their loader classes
SUPPORTED_EXTENSIONS: dict[str, type] = {
    ".pdf": PyPDFLoader,
    ".docx": Docx2txtLoader,
    ".doc": Docx2txtLoader,
    ".txt": TextLoader,
    ".md": TextLoader,
    ".html": UnstructuredHTMLLoader,
    ".htm": UnstructuredHTMLLoader,
    ".pptx": UnstructuredPowerPointLoader,
}


class DocumentProcessor:
    """Processes documents from ZIP files into chunks for vector storage."""

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        """
        Initialize the document processor.

        Args:
            chunk_size: Maximum size of each text chunk
            chunk_overlap: Overlap between consecutive chunks
        """
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    def get_supported_formats(self) -> str:
        """Get a comma-separated string of supported formats."""
        formats = set()
        for ext in SUPPORTED_EXTENSIONS.keys():
            formats.add(ext.upper().replace(".", ""))
        return ", ".join(sorted(formats))

    def process_zip(
        self, zip_path: Path
    ) -> Generator[tuple[str, list[Document] | None, str | None], None, None]:
        """
        Extract and process documents from a ZIP file.

        Args:
            zip_path: Path to the ZIP file

        Yields:
            Tuples of (filename, chunks, error_message)
            - If successful: (filename, chunks, None)
            - If failed: (filename, None, error_message)
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Extract ZIP
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(temp_path)
            except zipfile.BadZipFile:
                yield ("", None, "Неверный ZIP-архив")
                return

            # Find all files
            files_found = False
            for file_path in temp_path.rglob("*"):
                # Skip directories and hidden files
                if file_path.is_dir():
                    continue
                if file_path.name.startswith("."):
                    continue
                if "__MACOSX" in str(file_path):
                    continue

                ext = file_path.suffix.lower()

                # Skip unsupported formats silently
                if ext not in SUPPORTED_EXTENSIONS:
                    continue

                files_found = True
                relative_name = file_path.name

                try:
                    # Get the appropriate loader
                    loader_class = SUPPORTED_EXTENSIONS[ext]
                    loader = loader_class(str(file_path))

                    # Load document
                    docs = loader.load()

                    if not docs:
                        yield (relative_name, None, "Пустой документ")
                        continue

                    # Add source metadata
                    for doc in docs:
                        doc.metadata["source"] = relative_name

                    # Split into chunks
                    chunks = self.splitter.split_documents(docs)

                    yield (relative_name, chunks, None)

                except Exception as e:
                    logger.error(f"Failed to process {relative_name}: {e}")
                    yield (relative_name, None, f"Ошибка обработки: {str(e)[:50]}")

            if not files_found:
                yield ("", None, "Не найдено поддерживаемых документов")

    def process_single_file(
        self, file_path: Path
    ) -> tuple[list[Document] | None, str | None]:
        """
        Process a single document file.

        Args:
            file_path: Path to the document

        Returns:
            Tuple of (chunks, error_message)
        """
        ext = file_path.suffix.lower()

        if ext not in SUPPORTED_EXTENSIONS:
            return None, f"Неподдерживаемый формат: {ext}"

        try:
            loader_class = SUPPORTED_EXTENSIONS[ext]
            loader = loader_class(str(file_path))
            docs = loader.load()

            if not docs:
                return None, "Пустой документ"

            for doc in docs:
                doc.metadata["source"] = file_path.name

            chunks = self.splitter.split_documents(docs)
            return chunks, None

        except Exception as e:
            logger.error(f"Failed to process {file_path}: {e}")
            return None, f"Ошибка: {str(e)[:50]}"
