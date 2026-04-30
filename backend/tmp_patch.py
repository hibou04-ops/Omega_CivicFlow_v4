import sys

with open('c:/Users/hibou/Omega_CivicFlow_v4/backend/services/chat_agent_safe_service.py', 'r', encoding='utf-8') as f:
    text = f.read()

start_marker = 'route = params.get("route") or variables.get("route") or ROUTE_QA'
end_marker = '        return {\n            "reply": llm_reply,\n            "payload": payload,\n            "tools_used": tools_used,\n        }'

start_idx = text.find(start_marker)
end_idx = text.find(end_marker) + len(end_marker)

if start_idx != -1 and end_idx != -1:
    new_code = '''route = params.get("route") or variables.get("route") or ROUTE_QA

        # ═══════════════════════════════════════════════════════
        # OMEGA-PRIME MULTI-AGENT ORCHESTRATOR
        # ═══════════════════════════════════════════════════════
        from agents.llm_client import OllamaLLMClient
        from agents.schemas import Message
        from agents.orchestrator import AgentOrchestrator
        from services.agent_retrieval import CivicFlowRetriever

        messages = []
        for h in history:
            role = "user" if h.get("sender") == "user" else "assistant"
            messages.append(Message(role=role, content=h.get("text", "")))
        
        llm = OllamaLLMClient()
        retriever = CivicFlowRetriever(db)
        orchestrator = AgentOrchestrator(llm=llm, retriever=retriever)
        
        response = await orchestrator.run(user_message, messages)
        
        return {
            "reply": response.answer,
            "payload": None,
            "tools_used": ["omega_prime_orchestrator"] if response.used_retrieval else ["direct_answer"],
        }'''
    
    new_text = text[:start_idx] + new_code + text[end_idx:]
    with open('c:/Users/hibou/Omega_CivicFlow_v4/backend/services/chat_agent_safe_service.py', 'w', encoding='utf-8') as f:
        f.write(new_text)
    print('PATCHED')
else:
    print('MARKERS NOT FOUND')
