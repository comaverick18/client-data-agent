# src/rag_engine.py
# RAG engine: loads reference documents into ChromaDB and answers semantic queries
# Agent 2 calls query_rag() to retrieve best-practice field definitions

import os
from dotenv import load_dotenv
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

load_dotenv()

# Where ChromaDB will store its index on disk
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROMA_PERSIST_DIR = os.path.join(BASE_DIR, "data", "chroma_db")
RAG_DOCS_DIR = os.path.join(BASE_DIR, "data", "rag_docs")

def build_vector_store() -> Chroma:
    """
    Load all .txt files from data/rag_docs/, chunk them, embed them,
    and store in ChromaDB. Call this once to initialize.
    
    Think of it as: reading a textbook and creating a searchable index.
    """
    print("📚 Loading RAG reference documents...")
    
    # Load all .txt files in the rag_docs directory
    loader = DirectoryLoader(
        RAG_DOCS_DIR,
        glob="**/*.txt",
        loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"}
    )
    documents = loader.load()
    print(f"   Loaded {len(documents)} document(s)")

    # Split into chunks — ChromaDB stores chunks, not full docs
    # chunk_size=500: each chunk is ~500 characters
    # chunk_overlap=50: chunks share 50 chars with neighbors (preserves context at edges)
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_documents(documents)
    print(f"   Split into {len(chunks)} chunks")

    # Embeddings: sentence-transformers runs locally, no API key needed
    # "all-MiniLM-L6-v2" is small, fast, and good enough for our use case
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

    # Build ChromaDB index and persist to disk
    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=CHROMA_PERSIST_DIR
    )
    print(f"✅ Vector store built and saved to {CHROMA_PERSIST_DIR}")
    return vectorstore


def load_vector_store() -> Chroma:
    """
    Load an already-built ChromaDB index from disk.
    Call this on subsequent runs (after build_vector_store() has been called once).
    """
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    return Chroma(
        persist_directory=CHROMA_PERSIST_DIR,
        embedding_function=embeddings
    )


def query_rag(query: str, k: int = 3) -> str:
    """
    The main function Agent 2 will call.
    Takes a question, finds the k most relevant chunks, returns them as a string.
    
    Example: query_rag("What are required fields for CRM data?")
    Returns the 3 most relevant chunks from our reference docs.
    """
    # Load from disk if it exists, build if it doesn't
    if os.path.exists(CHROMA_PERSIST_DIR) and os.listdir(CHROMA_PERSIST_DIR):
        vectorstore = load_vector_store()
    else:
        vectorstore = build_vector_store()

    results = vectorstore.similarity_search(query, k=k)
    
    # Combine chunks into one string for the LLM to read
    combined = "\n\n---\n\n".join([doc.page_content for doc in results])
    return combined


# --- Quick test ---
if __name__ == "__main__":
    # First run: builds the index. Subsequent runs: loads from disk.
    result = query_rag("What are the required fields for CRM data?")
    print("Query result:\n")
    print(result)