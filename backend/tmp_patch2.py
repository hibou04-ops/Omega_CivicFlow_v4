import sys
import re

with open('c:/Users/hibou/Omega_CivicFlow_v4/backend/agents/orchestrator.py', 'r', encoding='utf-8') as f:
    text = f.read()

# We want to add a _sanitize_text helper
new_code = '''        if critic.passed:
            logger.info("[Orchestrator] Critic passed cleanly.")
            final_answer = draft
        else:
            logger.info(f"[Orchestrator] Critic failed. Issues: {critic.issues}. Revising...")
            final_answer = await self.llm.complete_text(
                system_prompt=CORE_SYSTEM_PROMPT,
                user_prompt=build_reviser_prompt(
                    draft_answer=draft,
                    critic=critic,
                ),
                temperature=0.2,
            )

        # Force unwrap JSON if the model stubbornly returns a JSON object
        final_answer = final_answer.strip()
        if final_answer.startswith("{") and final_answer.endswith("}"):
            try:
                import json
                data = json.loads(final_answer)
                # If it's a dict, just take the first string value (like message or 결론)
                if isinstance(data, dict) and data:
                    for val in data.values():
                        if isinstance(val, str):
                            final_answer = val
                            break
            except Exception:
                pass
        elif final_answer.startswith("```json"):
            # Strip markdown json block
            final_answer = re.sub(r"```(?:json)?(.*?)```", r"\\1", final_answer, flags=re.DOTALL).strip()
            if final_answer.startswith("{") and final_answer.endswith("}"):
                try:
                    import json
                    data = json.loads(final_answer)
                    if isinstance(data, dict) and data:
                        for val in data.values():
                            if isinstance(val, str):
                                final_answer = val
                                break
                except Exception:
                    pass

        return ChatResponse(
            answer=final_answer,
            route=route,
            used_retrieval=True,
            evidence_count=len(filtered_chunks),
        )'''

start_marker = "if critic.passed:"
end_marker = "evidence_count=len(filtered_chunks),\n        )"

start_idx = text.find(start_marker)
end_idx = text.find(end_marker) + len(end_marker)

if start_idx != -1 and end_idx != -1:
    new_text = text[:start_idx] + new_code + text[end_idx:]
    with open('c:/Users/hibou/Omega_CivicFlow_v4/backend/agents/orchestrator.py', 'w', encoding='utf-8') as f:
        f.write(new_text)
    print("PATCHED")
else:
    print("NOT FOUND")
