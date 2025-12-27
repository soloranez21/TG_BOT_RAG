"""
RAG Chain - handles vector storage and retrieval-augmented generation.
"""
import logging
from typing import Optional

from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_qdrant import QdrantVectorStore
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_core.documents import Document
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

logger = logging.getLogger(__name__)

# Prompt template for RAG queries
RAG_PROMPT = ChatPromptTemplate.from_template("""
Answer the question based only on the following context.
If you cannot find the answer in the context, say "I couldn't find relevant information in your documents."

Context:
{context}

Question: {question}

Answer:""")


class RAGChain:
    """Manages vector storage and RAG queries."""

    def __init__(
        self,
        openai_key: str,
        qdrant_url: str,
        collection_name: str,
        embedding_model: str = "text-embedding-3-small",
        llm_model: str = "gpt-4o-mini",
    ):
        """
        Initialize the RAG chain.

        Args:
            openai_key: OpenAI API key
            qdrant_url: Qdrant server URL
            collection_name: Name of the Qdrant collection
            embedding_model: OpenAI embedding model to use
            llm_model: OpenAI chat model to use
        """
        self.openai_key = openai_key
        self.qdrant_url = qdrant_url
        self.collection_name = collection_name

        # Initialize embeddings
        self.embeddings = OpenAIEmbeddings(
            model=embedding_model,
            api_key=openai_key,
        )

        # Initialize LLM
        self.llm = ChatOpenAI(
            model=llm_model,
            api_key=openai_key,
            temperature=0.3,
        )

        # Initialize Qdrant client
        self.qdrant_client = QdrantClient(url=qdrant_url)

        # Vector store (initialized after ensuring collection exists)
        self.vectorstore: Optional[QdrantVectorStore] = None

        # Ensure collection exists
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """Create the Qdrant collection if it doesn't exist."""
        try:
            collections = [
                c.name for c in self.qdrant_client.get_collections().collections
            ]

            if self.collection_name not in collections:
                self.qdrant_client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=1536,  # text-embedding-3-small dimension
                        distance=Distance.COSINE,
                    ),
                )
                logger.info(f"Created collection: {self.collection_name}")

            # Initialize vector store
            self.vectorstore = QdrantVectorStore(
                client=self.qdrant_client,
                collection_name=self.collection_name,
                embedding=self.embeddings,
            )

        except Exception as e:
            logger.error(f"Failed to ensure collection: {e}")
            raise

    def add_documents(self, documents: list[Document]) -> int:
        """
        Add documents to the vector store.

        Args:
            documents: List of LangChain documents to add

        Returns:
            Number of documents added
        """
        if not documents:
            return 0

        try:
            self.vectorstore.add_documents(documents)
            logger.info(f"Added {len(documents)} chunks to {self.collection_name}")
            return len(documents)
        except Exception as e:
            logger.error(f"Failed to add documents: {e}")
            raise

    def get_stats(self) -> tuple[int, int]:
        """
        Get collection statistics.

        Returns:
            Tuple of (estimated_doc_count, chunk_count)
        """
        try:
            info = self.qdrant_client.get_collection(self.collection_name)
            chunk_count = info.points_count

            # Estimate document count (rough: assume ~10 chunks per doc)
            doc_count = max(1, chunk_count // 10) if chunk_count > 0 else 0

            return doc_count, chunk_count
        except Exception:
            return 0, 0

    def clear(self) -> None:
        """Delete all documents from the collection."""
        try:
            self.qdrant_client.delete_collection(self.collection_name)
            self._ensure_collection()
            logger.info(f"Cleared collection: {self.collection_name}")
        except Exception as e:
            logger.error(f"Failed to clear collection: {e}")
            raise

    def query(self, question: str, k: int = 5) -> tuple[str, list[str]]:
        """
        Query the RAG chain.

        Args:
            question: The user's question
            k: Number of chunks to retrieve

        Returns:
            Tuple of (answer, list of source document names)
        """
        try:
            logger.info(f"[QUERY] Starting query: {question[:50]}...")
            
            # Create retriever
            logger.info(f"[QUERY] Creating retriever with k={k}")
            retriever = self.vectorstore.as_retriever(
                search_kwargs={"k": k}
            )

            # Retrieve relevant documents
            logger.info(f"[QUERY] Retrieving relevant documents...")
            relevant_docs = retriever.invoke(question)
            logger.info(f"[QUERY] Found {len(relevant_docs)} relevant documents")

            if not relevant_docs:
                logger.warning(f"[QUERY] No relevant documents found")
                return (
                    "Я не нашёл релевантной информации в ваших документах.",
                    [],
                )

            # Extract unique sources
            sources = list(set(
                doc.metadata.get("source", "Неизвестный источник")
                for doc in relevant_docs
            ))
            logger.info(f"[QUERY] Sources: {sources}")

            # Format context
            def format_docs(docs: list[Document]) -> str:
                return "\n\n".join(doc.page_content for doc in docs)

            # Build and execute chain
            logger.info(f"[QUERY] Building RAG chain...")
            chain = (
                {
                    "context": retriever | format_docs,
                    "question": RunnablePassthrough(),
                }
                | RAG_PROMPT
                | self.llm
                | StrOutputParser()
            )

            logger.info(f"[QUERY] Invoking chain with LLM...")
            answer = chain.invoke(question)
            logger.info(f"[QUERY] Got answer: {answer[:100]}...")

            return answer, sources

        except Exception as e:
            logger.error(f"[QUERY] Query failed: {e}")
            logger.exception(e)
            return (
                "Произошла ошибка при обработке запроса. Попробуйте ещё раз.",
                [],
            )

    def similarity_search(
        self, query: str, k: int = 5
    ) -> list[tuple[Document, float]]:
        """
        Perform similarity search and return documents with scores.

        Args:
            query: Search query
            k: Number of results

        Returns:
            List of (document, score) tuples
        """
        try:
            results = self.vectorstore.similarity_search_with_score(query, k=k)
            return results
        except Exception as e:
            logger.error(f"Similarity search failed: {e}")
            return []
