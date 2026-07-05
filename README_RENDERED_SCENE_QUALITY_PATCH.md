# Rendered Scene Quality Patch

Apply over current repository, redeploy Railway, then re-import /openapi.json.

Fixes:
- applyTurnResult returns message_to_user/rendered_text.
- scene_response_normalizer rebuilds rendered_text if header/body/footer are missing.
- turn_processor asks for fuller scenes and meaningful choice endings.

Custom GPT line:
After applyTurnResult, final answer to user = response.message_to_user exactly.
