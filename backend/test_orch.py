import asyncio
from agents.llm_client import OllamaLLMClient
from agents.orchestrator import AgentOrchestrator
from services.agent_retrieval import Retriever
from agents.schemas import RetrievedChunk

class DummyRetriever(Retriever):
    async def search(self, queries, top_k=8):
        return []

async def test():
    llm = OllamaLLMClient()
    orchestrator = AgentOrchestrator(llm, DummyRetriever())
    
    print("Testing easy query...")
    res = await orchestrator.run("안녕, 반가워!", [])
    print("REPLY:", res.answer)

if __name__ == "__main__":
    asyncio.run(test())
