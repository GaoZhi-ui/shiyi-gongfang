"""
向量知识库模块（RAG 2.0）

使用 ChromaDB 作为本地持久化向量数据库 + sentence-transformers 作为嵌入模型。
支持多项目隔离（每个 project_id 一个 collection）。

向量分块策略：
  - 每 500 字一个块
  - 重叠 50 字
  - 确保上下文不丢失

嵌入模型：all-MiniLM-L6-v2（轻量 ~80MB）
"""

import re
import logging
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

logger = logging.getLogger("vector_store")

# ─── 全局单例 ───

_vector_store_instance: Optional["VectorStore"] = None


def get_vector_store() -> "VectorStore":
    """获取全局 VectorStore 单例"""
    global _vector_store_instance
    if _vector_store_instance is None:
        _vector_store_instance = VectorStore()
    return _vector_store_instance


# ─── 分块策略 ───

CHUNK_SIZE = 500       # 每块字符数
CHUNK_OVERLAP = 50     # 块间重叠字符数


def _split_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """将文本按字符数分块，块间重叠指定字符数"""
    if not text:
        return []
    # 按段落分割，保留段落结构
    paragraphs = text.split("\n")
    chunks = []
    current_chunk = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # 如果当前块 + 新段落不超过 chunk_size，直接追加
        if len(current_chunk) + len(para) + 1 <= chunk_size:
            if current_chunk:
                current_chunk += "\n" + para
            else:
                current_chunk = para
        else:
            # 当前块满了，先保存
            if current_chunk:
                chunks.append(current_chunk)
            # 如果段落本身超过 chunk_size，硬切
            if len(para) > chunk_size:
                pos = 0
                while pos < len(para):
                    chunk = para[pos:pos + chunk_size]
                    chunks.append(chunk)
                    pos += chunk_size - overlap
                current_chunk = ""
            else:
                current_chunk = para

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _strip_frontmatter(content: str) -> str:
    """去除 YAML frontmatter，返回纯正文"""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return content


# ─── VectorStore ───


class VectorStore:
    """向量知识库，使用 ChromaDB + sentence-transformers"""

    def __init__(self, persist_dir: Optional[str] = None):
        """
        初始化向量库。

        Args:
            persist_dir: ChromaDB 持久化目录，默认在 data/vector_db 下
        """
        if persist_dir is None:
            # 默认放在项目 data/ 下
            base = Path(__file__).resolve().parent.parent / "data"
            base.mkdir(parents=True, exist_ok=True)
            persist_dir = str(base / "vector_db")

        self._persist_dir = persist_dir
        self._client: Optional[chromadb.PersistentClient] = None
        self._encoder: Optional[SentenceTransformer] = None
        self._project_collections: dict[str, chromadb.Collection] = {}

        logger.info(f"VectorStore 持久化目录: {persist_dir}")

    # ─── 延迟初始化 ───

    def _ensure_client(self):
        """确保 ChromaDB 客户端已初始化"""
        if self._client is None:
            self._client = chromadb.PersistentClient(
                path=self._persist_dir,
                settings=Settings(anonymized_telemetry=False),
            )

    def _ensure_encoder(self):
        """确保嵌入模型已加载（支持 HuggingFace 镜像 fallback）"""
        if self._encoder is None:
            model_name = "all-MiniLM-L6-v2"
            logger.info(f"正在加载嵌入模型 {model_name} ...")

            # 尝试常用 HuggingFace 国内镜像
            mirrors = [
                None,  # 直连
                "https://hf-mirror.com",
                "https://huggingface.sdccn.com.cn",
            ]

            last_error = None
            for mirror in mirrors:
                try:
                    import os as _os
                    if mirror:
                        _os.environ["HF_ENDPOINT"] = mirror
                    else:
                        _os.environ.pop("HF_ENDPOINT", None)

                    self._encoder = SentenceTransformer(model_name)
                    logger.info(f"嵌入模型加载完成 (mirror={mirror or 'direct'})")
                    return
                except Exception as e:
                    last_error = e
                    logger.warning(f"嵌入模型加载失败 (mirror={mirror or 'direct'}): {e}")
                    continue

            # 所有镜像都失败：尝试离线模式/使用小型 fallback
            logger.error(f"嵌入模型全部加载失败: {last_error}")
            raise RuntimeError(
                f"无法加载嵌入模型 {model_name}。请检查网络连接或手动下载模型。"
            ) from last_error

    def _get_collection_name(self, project_id: str) -> str:
        """规范化 collection 名称（ChromaDB 要求小写字母、数字、下划线、连字符）"""
        # 替换非法字符为下划线
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", project_id)
        return safe

    # ─── 公开 API ───

    def init_store(self, project_id: str):
        """
        初始化/加载项目向量库 collection。

        Args:
            project_id: 项目标识符
        """
        self._ensure_client()
        collection_name = self._get_collection_name(project_id)

        if collection_name in self._project_collections:
            return

        try:
            collection = self._client.get_collection(name=collection_name)
            logger.info(f"加载已有 collection: {collection_name}")
        except Exception:
            collection = self._client.create_collection(name=collection_name)
            logger.info(f"创建新 collection: {collection_name}")

        self._project_collections[collection_name] = collection

    def _get_collection(self, project_id: str) -> chromadb.Collection:
        """获取项目的 collection（确保已初始化）"""
        collection_name = self._get_collection_name(project_id)
        if collection_name not in self._project_collections:
            self.init_store(project_id)
        return self._project_collections[collection_name]

    # ─── 添加内容 ───

    def add_chapter(self, project_id: str, filename: str, title: str, content: str):
        """
        将章节内容分块后向量化存入。

        Args:
            project_id: 项目标识符
            filename: 章节文件名（如 第1章_开端.md）
            title: 章节标题
            content: 章节正文（含 frontmatter 会自动剥离）
        """
        self._ensure_encoder()
        collection = self._get_collection(project_id)

        # 剥离 YAML frontmatter，只向量化正文
        body = _strip_frontmatter(content)

        # 分块
        chunks = _split_text(body)
        if not chunks:
            logger.warning(f"章节内容为空，跳过向量化: {filename}")
            return

        # 删除旧向量（同名文件已存在时覆盖）
        self.delete_chapter(project_id, filename)

        # 生成嵌入
        embeddings = self._encoder.encode(chunks, show_progress_bar=False).tolist()

        ids = []
        metadatas = []
        documents = []

        for i, chunk in enumerate(chunks):
            chunk_id = f"{filename}::chunk_{i}"
            ids.append(chunk_id)
            metadatas.append({
                "filename": filename,
                "title": title,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "project_id": project_id,
            })
            documents.append(chunk)

        collection.add(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
        )

        logger.info(f"已向量化章节 [{filename}] → {len(chunks)} 个块")

    def add_knowledge(self, project_id: str, filepath: str, content: str):
        """
        将知识库文件向量化。

        使用 "knowledge:" 前缀的 ID，与章节区分。

        Args:
            project_id: 项目标识符
            filepath: 知识库文件路径（相对路径）
            content: 文件内容
        """
        self._ensure_encoder()
        collection = self._get_collection(project_id)

        body = _strip_frontmatter(content)
        chunks = _split_text(body)
        if not chunks:
            return

        # 删除旧知识库向量
        self._delete_by_prefix(project_id, f"knowledge:{filepath}")

        embeddings = self._encoder.encode(chunks, show_progress_bar=False).tolist()

        ids = []
        metadatas = []
        documents = []

        for i, chunk in enumerate(chunks):
            chunk_id = f"knowledge:{filepath}::chunk_{i}"
            ids.append(chunk_id)
            metadatas.append({
                "source": "knowledge",
                "filepath": filepath,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "project_id": project_id,
            })
            documents.append(chunk)

        collection.add(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
        )

        logger.info(f"已向量化知识库文件 [{filepath}] → {len(chunks)} 个块")

    # ─── 搜索 ───

    def search(self, query: str, project_id: str, top_k: int = 5) -> list[dict]:
        """
        搜索最相关的章节片段。

        Args:
            query: 搜索查询文本
            project_id: 项目标识符
            top_k: 返回 topK 结果

        Returns:
            结果列表，每项包含:
              - filename: 来源文件名
              - title: 章节标题
              - content: 片段内容
              - score: 相似度分数
              - chunk_index: 块索引
        """
        self._ensure_encoder()
        collection = self._get_collection(project_id)

        query_embedding = self._encoder.encode([query], show_progress_bar=False).tolist()[0]

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
        )

        output = []
        if not results["ids"] or not results["ids"][0]:
            return output

        for i in range(len(results["ids"][0])):
            metadata = results["metadatas"][0][i] if results["metadatas"] else {}
            doc = results["documents"][0][i] if results["documents"] else ""
            distance = results["distances"][0][i] if results["distances"] else 0.0

            output.append({
                "filename": metadata.get("filename", ""),
                "title": metadata.get("title", metadata.get("filepath", "")),
                "content": doc,
                "score": 1.0 - distance,  # 距离转相似度
                "chunk_index": metadata.get("chunk_index", 0),
            })

        return output

    # ─── 删除 ───

    def delete_chapter(self, project_id: str, filename: str):
        """删除章节的向量"""
        collection = self._get_collection(project_id)
        where = {"filename": filename}
        try:
            # 先查询有哪些记录
            existing = collection.get(where=where)
            if existing and existing.get("ids"):
                collection.delete(where=where)
                logger.info(f"已删除章节向量: {filename} ({len(existing['ids'])} 个块)")
        except Exception as e:
            logger.warning(f"删除章节向量时出错 [{filename}]: {e}")

    def _delete_by_prefix(self, project_id: str, prefix: str):
        """删除 ID 以指定前缀开头的所有向量"""
        collection = self._get_collection(project_id)
        try:
            existing = collection.get()
            if not existing or not existing.get("ids"):
                return
            to_delete = [id_ for id_ in existing["ids"] if id_.startswith(prefix)]
            if to_delete:
                collection.delete(ids=to_delete)
                logger.info(f"已删除前缀匹配向量: {prefix} ({len(to_delete)} 个块)")
        except Exception as e:
            logger.warning(f"删除前缀匹配时出错 [{prefix}]: {e}")

    # ─── 管理 ───

    def count_chunks(self, project_id: str) -> int:
        """统计项目向量库中的块数量"""
        collection = self._get_collection(project_id)
        count = collection.count()
        return count

    def list_collections(self) -> list[str]:
        """列出所有 collection 名称"""
        self._ensure_client()
        collections = self._client.list_collections()
        return [c.name for c in collections]
