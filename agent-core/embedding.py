import os
import glob
import tiktoken
from openai import OpenAI
import chromadb
from langchain_openai import OpenAIEmbeddings
from langchain_experimental.text_splitter import SemanticChunker
from rank_bm25 import BM25Okapi
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))) 
from log import *
from llama_index.core import SimpleDirectoryReader

# ============================
#     HELPER FUNCTIONS
# ============================

# tokenizer
enc = tiktoken.encoding_for_model("text-embedding-3-large")

def count_tokens(text):
    return len(enc.encode(text))

def safe_split_tokens(text, max_tokens=8000):
    """
    将超过 token 限制的 chunk 自动切分，保证 embedding 不报错
    """
    tokens = enc.encode(text)
    if len(tokens) <= max_tokens:
        return [text]

    chunks = []
    start = 0
    while start < len(tokens):
        sub = tokens[start:start + max_tokens]
        chunks.append(enc.decode(sub))
        start += max_tokens

    return chunks


# ============================
#    MAIN CLASS
# ============================
class EmbeddingModel:
    def __init__(self, linux_dir="./linux", case_dir="./case", persist_linux_dir="chroma_db", persist_case_dir="chroma_db", model="text-embedding-3-large", api_key=None):

        self.linux_dir = linux_dir
        self.case_dir = case_dir
        self.persist_linux_dir = persist_linux_dir
        self.persist_case_dir = persist_case_dir
        self.model_name = model

        # OpenAI
        self.client = OpenAI(api_key=api_key)

        # For SemanticChunker
        self.lc_embeddings = OpenAIEmbeddings(model=model, api_key=api_key)
        
        self.chroma_client = {}
        self.collection = {}

        # Chroma (Vector DB)
        self.chroma_client["linux"] = chromadb.PersistentClient(path=persist_linux_dir)
        self.collection["linux"] = self.chroma_client["linux"].get_or_create_collection(
            name="linux_src",
            metadata={"hnsw:space": "cosine"}
        )
        
        self.chroma_client["case"] = chromadb.PersistentClient(path=persist_case_dir)
        self.collection["case"] = self.chroma_client["case"].get_or_create_collection(
            name="case_info",
            metadata={"hnsw:space": "cosine"}
        )

        # Semantic chunker for linux source code
        self.semantic_chunker = SemanticChunker(
            self.lc_embeddings,
            breakpoint_threshold_type="percentile"
        )
        
        self.logger = get_logger("embedding")

        # For BM25
        self.bm25_docs = {}
        self.bm25_index = {}
        
        self.logger.info("EmbeddingModel initialized.")


    # ============================
    #   STEP 1: Load all files
    # ============================
    def load_from_linux(self):
        file_list = glob.glob(os.path.join(self.linux_dir, "**", "*.c"), recursive=True)

        docs = []
        for path in file_list:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            docs.append(text)

        return docs


    # ============================
    #   STEP 2: Semantic Chunking
    # ============================
    def semantic_chunk(self, text):
        docs = self.semantic_chunker.create_documents([text])
        return [d.page_content for d in docs]


    # ============================
    #   STEP 3: Embedding
    # ============================
    def embed(self, text):
        resp = self.client.embeddings.create(
            model=self.model_name,
            input=text
        )
        return resp.data[0].embedding


    # ============================
    #   STEP 4: Build Index
    # ============================
    def build_index_for_linux(self):
        self.logger.info("Loading linux src dataset...")
        docs = self.load_from_linux()
        self.logger.info(f"Loaded {len(docs)} files.")

        doc_id = 0
        bm25_corpus = []

        for text in docs:

            chunks = self.semantic_chunk(text)

            for chunk in chunks:

                # 自动不超 token，切分成多个安全片段
                safe_chunks = safe_split_tokens(chunk)

                for sub in safe_chunks:
                    emb = self.embed(sub)

                    # Add to vector DB
                    self.collection["linux"].add(
                        ids=[str(doc_id)],
                        documents=[sub],
                        embeddings=[emb]
                    )

                    # For BM25 index
                    bm25_corpus.append(sub.split())

                    doc_id += 1

        # Build BM25
        self.logger.info("Building BM25 index...")
        self.bm25_docs["linux"] = bm25_corpus
        self.bm25_index["linux"] = BM25Okapi(self.bm25_docs["linux"])
    
    # for case dataset, a file as a chunk
    def build_index_for_case(self):
        self.logger.info("Loading case dataset...")
        
        documents = SimpleDirectoryReader(
            self.case_dir,recursive=True
            ).load_data()
        
        bm25_corpus = []
        doc_id = 0
        
        for doc in documents:
            text = doc.page_content

            emb = self.embed(text)

            # Add to vector DB
            self.collection["case"].add(
                ids=[str(doc_id)],
                documents=[text],
                embeddings=[emb]
            )
            doc_id += 1
            
            bm25_corpus.append(text.split())
    
        # Build BM25
        self.logger.info("Building BM25 index for case...")
        self.bm25_docs["case"] = bm25_corpus
        self.bm25_index["case"] = BM25Okapi(self.bm25_docs["case"])

    # ============================
    #   STEP 5: Multi-Recall Search
    # ============================
    def search(self, query, top_k=5, target="linux"):

        # ================
        # 1. BM25 recall
        # ================
        tokens = query.split()
        bm25_scores = self.bm25_index[target].get_scores(tokens)
        bm25_top_ids = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[:top_k]

        bm25_hits = []
        for idx in bm25_top_ids:
            doc = self.collection[target].get(ids=[str(idx)])
            bm25_hits.append({
                "text": doc["documents"][0],
                "score": float(bm25_scores[idx]),
            })


        # =================
        # 2. Vector recall
        # =================
        query_vec = self.embed(query)
        vec_results = self.collection[target].query(
            query_embeddings=[query_vec],
            n_results=top_k
        )

        vector_hits = []
        for i in range(len(vec_results["documents"][0])):
            vector_hits.append({
                "text": vec_results["documents"][0][i],
                "score": float(vec_results["distances"][0][i])
            })


        # =================
        # 3. Merge results
        # =================
        merged = { item["text"]: item for item in bm25_hits }

        for item in vector_hits:
            merged[item["text"]] = item

        # merged is dict → convert to list
        final_hits = list(merged.values())

        # vector score 越小越相似，bm25 score 越大越好
        # 简易融合：BM25 加权 + 向量倒数加权
        for h in final_hits:
            bm25_s = h.get("score", 0)
            vec_s = h.get("score", 0)
            fused = bm25_s * 0.7 + (1.0 / (1.0 + vec_s)) * 0.3
            h["fused_score"] = fused

        # 排序
        final_hits.sort(key=lambda x: x["fused_score"], reverse=True)

        return final_hits[:top_k]



# ============================
#       Run standalone
# ============================
if __name__ == "__main__":
    em = EmbeddingModel(data_dir="./data",persist_dir="db")

    print(">>> Building index…")
    em.build_index()

    print(">>> Test search")
    hits = em.search("free bpf_map", top_k=3)
    for h in hits:
        print("---")
        print(f"[{h['filepath']}] score={h['score']:.4f}")
        print(h["text"])
