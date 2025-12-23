import os
from openai import OpenAI, BadRequestError
import chromadb
from langchain_openai import OpenAIEmbeddings
from rank_bm25 import BM25Okapi
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))) 
from log import *
from llama_index.core import SimpleDirectoryReader
import hashlib

def calc_md5(text: str):
    return hashlib.md5(text.encode("utf-8")).hexdigest()

# ============================
#    MAIN CLASS
# ============================
class EmbeddingModel:
    def __init__(self, data_dir="./case", persist_dir="chroma_db", model="text-embedding-3-large", api_key=None):

        self.logger = get_logger("embedding")
        self.data_dir = data_dir
        self.model_name = model
        self.client = None

        try:
            # OpenAI
            self.client = OpenAI(api_key=api_key)
            # Test the API key by making a simple request
            self.client.models.list()
        except Exception as e:
            self.logger.error(f"Failed to create OpenAI client: {e}")
            raise ValueError(f"Invalid API key or OpenAI connection failed: {e}")
        
        self.chroma_client = {}
        self.collection = {}

        # Chroma (Vector DB)
        self.chroma_client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.chroma_client.get_or_create_collection(
            name="case",
            metadata={"hnsw:space": "cosine"}
        )

        # For BM25
        self.bm25_docs = []
        self.bm25_index = []
        
        self.logger.info("EmbeddingModel initialized.")


    # ============================
    #   STEP 3: Embedding
    # ============================
    def embed(self, text):
        resp = self.client.embeddings.create(
            model=self.model_name,
            input=text
        )
        return resp.data[0].embedding
    
    def is_cached(self, text_hash):
        result = self.collection.get(
            where={"hash": text_hash},
            limit=1
        )
        
        return len(result["documents"]) > 0
    
    # for case dataset, a file as a chunk
    def build_index(self):
        self.logger.info("Loading case dataset...")
        
        documents = SimpleDirectoryReader(
            self.data_dir,recursive=True
            ).load_data()
        
        bm25_corpus = []
        
        doc_id = 0
        
        for doc in documents:
            text = doc.get_content()
            
            text_hash = calc_md5(text)
            
            if self.is_cached(text_hash):
                bm25_corpus.append(text.split())
                continue
            try:
                emb = self.embed(text)
            
            #Due to network err or too much tokens
            except BadRequestError:
                continue
            
            bm25_corpus.append(text.split())

            # Add to vector DB
            self.collection.add(
                ids=[str(doc_id)],
                documents=[text],
                embeddings=[emb],
                metadatas=[{"hash": text_hash}]
            )
            
            doc_id += 1
    
        # Build BM25
        self.logger.info("Building BM25 index for case...")
        self.bm25_docs = bm25_corpus
        self.bm25_index = BM25Okapi(self.bm25_docs)

    # ============================
    #   STEP 5: Multi-Recall Search
    # ============================
    def search(self, query, top_k=5):

        # ====================
        # 1. BM25 recall
        # ====================
        tokens = query.split()
        bm25_scores = self.bm25_index.get_scores(tokens)
        bm25_top_ids = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[:top_k]

        bm25_hits = []
        for idx in bm25_top_ids:
            doc = self.collection.get(ids=[str(idx)])
            bm25_hits.append({
                "text": doc["documents"][0],
                "bm25_score": float(bm25_scores[idx]),
            })

        # ====================
        # 2. Vector recall
        # ====================
        query_vec = self.embed(query)
        vec_results = self.collection.query(
            query_embeddings=[query_vec],
            n_results = top_k * 10
        )

        vector_hits = []
        for i in range(len(vec_results["documents"][0])):
            vector_hits.append({
                "text": vec_results["documents"][0][i],
                "vec_distance": float(vec_results["distances"][0][i])
            })

        # ====================
        # 3. Merge results
        # ====================
        merged = {}

        for item in bm25_hits:
            merged[item["text"]] = {
                "text": item["text"],
                "bm25_score": item["bm25_score"],
                "vec_distance": None
            }

        for item in vector_hits:
            if item["text"] not in merged:
                merged[item["text"]] = {
                    "text": item["text"],
                    "bm25_score": None,
                    "vec_distance": item["vec_distance"],
                }
            else:
                merged[item["text"]]["vec_distance"] = item["vec_distance"]

        # Compute final fused score
        final_hits = []
        for text, item in merged.items():
            bm25_s = item["bm25_score"] or 0.0
            dist = item["vec_distance"]
            vec_sim = 1 / (1 + dist) if dist is not None else 0.0

            fused = bm25_s * 0.7 + vec_sim * 0.3

            final_hits.append({
                "text": text,
                "bm25_score": bm25_s,
                "vec_distance": dist,
                "vec_sim": vec_sim,
                "fused_score": fused
            })

        final_hits.sort(key=lambda x: x["fused_score"], reverse=True)

        return final_hits[:top_k]




# ============================
#       Run standalone
# ============================
if __name__ == "__main__":
    
    crash = '''crash report'''
    
    api_key = "skxx"
    em = EmbeddingModel(data_dir="./data",persist_dir="./db",api_key=api_key)

    print(">>> Building index…")
    em.build_index()

    print(">>> Test search")
    hits = em.search(crash, top_k=3)
    for h in hits:
        print("-----------------------------------------------------------------")
        print(f"Score: {h['fused_score']}")
        print(h["text"])
