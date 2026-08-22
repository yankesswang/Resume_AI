"""Built-in domain profiles.

``ai_engineer`` is the original hard-coded standard, expressed as data.  It is
kept byte-for-byte faithful to the constants in ``experience.py``,
``engineering.py``, ``skills.py`` and ``education.py`` so that a job scored
through the generic engine lands on the same number it did before — the
existing 3179 stored scores and every calibration note in
docs/SCORING_ALGORITHM.md remain valid.

Do not "tidy" the keyword weights here.  They were tuned against the real
candidate pool (see the calibration notes in CLAUDE.md); the ones that look
oddly specific are the ones that were measured.
"""

from __future__ import annotations

from app.scoring.domain_profile import (
    CompetencySpec,
    DomainProfile,
    EcosystemSpec,
    EducationSpec,
    TierSpec,
)

# Mirrors experience.TIER_KEYWORDS exactly.
_AI_TIER_KEYWORDS: dict[str, dict[str, float]] = {
    "3": {
        "PyTorch": 1.5, "HuggingFace": 1.5, "Hugging Face": 1.5,
        "LoRA": 1.8, "QLoRA": 1.8, "Fine-tuning": 1.8, "Fine tuning": 1.8,
        "SFT": 1.5, "PEFT": 1.8, "RLHF": 2.0, "DPO": 1.8,
        "Quantization": 1.5, "GGUF": 1.5, "AWQ": 1.5, "GPTQ": 1.5,
        "BitsAndBytes": 1.5, "Llama": 1.2, "Mistral": 1.2,
        "Training": 1.0, "Loss Function": 1.5, "Learning Rate": 1.2,
        "Gradient": 1.2, "Backpropagation": 1.2,
        "vLLM": 2.5, "TensorRT-LLM": 2.5, "TensorRT": 2.5, "TGI": 2.0,
        "CUDA": 2.5, "Flash Attention": 2.5, "KV Cache": 2.0,
        "Speculative Decoding": 2.0, "GPU Optimization": 2.0,
        "NCCL": 2.0, "DeepSpeed": 2.0, "Megatron": 2.0,
        "Model Parallelism": 2.0, "Tensor Parallelism": 2.0,
        "Triton Inference": 2.0,
    },
    "2": {
        "Vector Database": 1.5, "Milvus": 1.5, "Qdrant": 1.5,
        "Pinecone": 1.5, "Chroma": 1.2, "Weaviate": 1.5,
        "RAG": 1.8, "Retrieval Augmented": 1.8,
        "Embedding": 1.2, "Embedding optimization": 1.5,
        "Hybrid Search": 1.5, "Reranking": 1.5, "HyDE": 1.5,
        "Function Calling": 1.5, "ReAct": 1.5, "GraphRAG": 1.8,
        "Agent": 1.2, "LlamaIndex": 1.2, "LangGraph": 1.5,
        "Context Window": 1.2, "Hallucination": 1.2,
    },
    "1": {
        "OpenAI API": 1.0, "OpenAI": 0.8, "Claude API": 1.0,
        "Prompt Engineering": 1.0, "Prompt": 0.5,
        "Streamlit": 0.8, "Gradio": 0.8,
        "LangChain": 1.0, "Chatbot": 0.8, "ChatGPT": 0.5,
        "GPT-4": 0.8, "GPT-3": 0.8, "API": 0.3,
    },
}


def ai_engineer_profile() -> DomainProfile:
    """The preserved AI-engineer standard."""
    return DomainProfile(
        profile_id="builtin:ai-engineer",
        name="AI 工程師（內建校準標準）",
        domain="AI / 機器學習工程",
        summary=(
            "以 LLM / 深度學習為核心的 AI 工程職位，重視模型層級的實作深度、"
            "工程落地能力，以及可驗證的專案成效。"
        ),
        source="builtin",
        tiers=[
            TierSpec(
                level=0, label="Non-AI",
                definition=(
                    "履歷中沒有任何 AI/ML 實作證據。一般軟體開發、IT 支援、QA、"
                    "硬體或韌體工作皆屬此級。"
                ),
                evidence_examples=["純網頁開發", "IT 維運", "測試工程"],
            ),
            TierSpec(
                level=1, label="Wrapper",
                definition=(
                    "呼叫現成 AI API 完成應用，未觸及模型本身。"
                    "以 prompt 設計、串接 OpenAI/Claude API、聊天機器人為主。"
                ),
                evidence_examples=["OpenAI API 串接", "Prompt Engineering", "LangChain 應用"],
            ),
            TierSpec(
                level=2, label="RAG Architect",
                definition=(
                    "設計檢索增強生成或 Agent 系統：向量資料庫選型、切塊與嵌入策略、"
                    "重排序、混合檢索、工具呼叫流程。"
                ),
                evidence_examples=["RAG pipeline 設計", "向量資料庫（Milvus/Qdrant）", "Reranking / Hybrid Search"],
            ),
            TierSpec(
                level=3, label="AI Expert",
                definition=(
                    "直接操作模型本身：訓練、微調（LoRA/QLoRA/SFT/RLHF）、量化、"
                    "或推論效能優化（vLLM/TensorRT/CUDA kernel）。"
                ),
                evidence_examples=["LoRA 微調", "vLLM 推論優化", "CUDA / Flash Attention"],
            ),
        ],
        tier_keywords=_AI_TIER_KEYWORDS,
        # Mirrors engineering.py's three axes and their score weights
        # (0.35 / 0.20 / 0.15 at level 3 → 0.5 / 0.286 / 0.214 normalised).
        competencies=[
            CompetencySpec(
                key="backend", label="後端工程", weight=0.35,
                levels={
                    "3": ["Kubernetes", "K8s", "RabbitMQ", "Kafka", "Redis", "Celery",
                          "gRPC", "微服務", "microservice", "Golang", "Rust",
                          "Message Queue", "高併發", "load balanc"],
                    "2": ["Asyncio", "async", "Docker", "Gunicorn", "Uvicorn", "Nginx",
                          "CI/CD", "GitHub Actions", "GitLab CI", "容器", "container",
                          "reverse proxy", "反向代理"],
                    "1": ["Flask", "FastAPI", "Django", "REST API", "Express",
                          "Spring Boot", "後端", "backend"],
                },
            ),
            CompetencySpec(
                key="database", label="資料庫", weight=0.20,
                levels={
                    "3": ["pgvector", "Milvus", "Qdrant", "Pinecone", "Weaviate",
                          "Chroma", "Vector DB", "向量資料庫", "Neo4j", "Graph DB",
                          "HNSW", "IVF"],
                    "2": ["PostgreSQL", "MongoDB", "SQLAlchemy", "Airflow",
                          "Elasticsearch", "NoSQL", "ORM", "ETL", "Redis",
                          "資料清理", "data pipeline"],
                    "1": ["MySQL", "SQLite", "SQL", "CSV", "Pandas", "資料庫", "database"],
                },
            ),
            CompetencySpec(
                key="frontend", label="前端", weight=0.15,
                levels={
                    "3": ["React", "Vue", "Next.js", "Nuxt", "Angular", "TypeScript",
                          "Tailwind", "SSE", "Server-Sent Event", "前端框架"],
                    "2": ["HTML", "CSS", "Bootstrap", "JavaScript", "jQuery",
                          "前端", "web develop", "網頁"],
                    "1": ["Streamlit", "Gradio", "Dash", "Panel", "Chainlit"],
                },
            ),
        ],
        education=EducationSpec(
            tier1_majors=["資工", "資訊工程", "資管", "資訊管理", "電機", "EECS",
                          "Computer Science", "MIS", "AI", "Artificial Intelligence",
                          "Data Science", "資訊科學", "Machine Learning",
                          "軟體工程", "Software Engineering", "電信工程"],
            tier2_majors=["統計", "數學", "應數", "數據", "理學院", "Math", "Stat",
                          "Physics", "物理", "應用數學", "Applied Math",
                          "Operations Research", "工業工程"],
        ),
        # Mirrors skills.py's ecosystem patterns and config.skills.ecosystem_scores.
        ecosystems=[
            EcosystemSpec(
                name="LLM Stack", score=90,
                keywords=["LangChain", "LlamaIndex", "vLLM", "Ollama", "OpenAI",
                          "Claude", "LLM", "GPT", "Llama", "Mistral", "RAG",
                          "Prompt", "Fine-tun", "LoRA", "QLoRA", "PEFT",
                          "Embedding", "Vector", "RLHF", "DPO",
                          "大型語言模型", "語言模型"],
            ),
            EcosystemSpec(
                name="Deep Learning", score=70,
                keywords=["PyTorch", "TensorFlow", "Keras", "Jax", "CNN", "RNN",
                          "LSTM", "GAN", "Transformer", "Attention", "BERT",
                          "ResNet", "YOLO", "Neural Network", "深度學習", "神經網路"],
            ),
            EcosystemSpec(
                name="Traditional ML", score=50,
                keywords=["Sklearn", "scikit-learn", "XGBoost", "LightGBM",
                          "CatBoost", "Random Forest", "SVM", "Logistic Regression",
                          "Decision Tree", "Feature Engineering", "特徵工程"],
            ),
            EcosystemSpec(name="General", score=30, keywords=[]),
        ],
    )


BUILTIN_PROFILES = {
    "builtin:ai-engineer": ai_engineer_profile,
}


def get_builtin(profile_id: str):
    factory = BUILTIN_PROFILES.get(profile_id)
    return factory() if factory else None
