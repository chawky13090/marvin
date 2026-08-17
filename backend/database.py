"""
SecretaryAI Backend — Couche base de données SQLite.
Source de vérité pour data/secretary.db (v2.111 : le frontend Next.js n'y accède plus
en direct que pour getSetting/setSetting — conversations/notes/tasks/projects/mémoire
passent tous par ce module via des proxys /api/*, voir le changelog v2.107-111 dans
CLAUDE.md §9 pour le détail de cette consolidation).
Utilise le module sqlite3 standard de Python (thread-safe avec check_same_thread=False).
"""
from db_connection import db
from database_bootstrap import initialize_database
from repositories.billing import (
    billing_catalog_create,
    billing_catalog_delete,
    billing_catalog_list,
    billing_client_create,
    billing_client_delete,
    billing_client_get,
    billing_client_list,
    billing_client_update,
    billing_contract_create,
    billing_contract_list,
    billing_invoice_create,
    billing_invoice_delete,
    billing_invoice_get,
    billing_invoice_list,
    billing_invoice_update,
    billing_quote_create,
    billing_quote_delete,
    billing_quote_get,
    billing_quote_list,
    billing_quote_update,
)
from repositories.conversations import (
    create_conversation,
    create_message,
    delete_conversation,
    get_conversation,
    get_messages_by_conversation,
    get_messages_page,
    get_message,
    has_messages_before,
    get_messages_for_context,
    get_recent_user_messages,
    list_conversations,
    search_conversations,
    set_conversation_archived,
    set_conversation_pinned,
    update_conversation_project,
    update_conversation_title,
    upgrade_conversation_title_silent,
)
from repositories.client_health import (
    health_recommendations_list,
    health_score_create,
    health_score_get,
    health_score_history,
    health_score_latest,
)
from repositories.command_safety import (
    approval_create,
    approval_decide,
    approval_list,
    cmd_review_create,
    cmd_review_list,
    cmd_rules_list,
)
from repositories.cron_jobs import (
    create_cron_job,
    delete_cron_job,
    get_cron_job,
    list_cron_jobs,
    update_cron_job,
)
from repositories.documentation import (
    doc_asset_create,
    doc_asset_delete,
    doc_asset_list,
    doc_document_create,
    doc_document_delete,
    doc_document_list,
    doc_intervention_create,
    doc_intervention_delete,
    doc_intervention_get,
    doc_intervention_list,
    doc_intervention_update,
    doc_template_get,
    doc_template_list,
    doc_template_use,
)
from repositories.events import (
    count_events_by_source,
    create_event,
    delete_event,
    delete_events_by_source,
    events_needing_reminder,
    get_event,
    list_events,
    replace_external_events,
    update_event,
)
from repositories.executions import (
    get_conversation_trace,
    get_request_trace,
    get_execution_stats,
    get_tool_reliability,
    list_executions,
    log_execution,
)
from repositories.flashcards import (
    answer_flashcard,
    create_flashcard,
    delete_flashcards_by_topic,
    flashcard_stats,
    get_next_flashcard,
)
from repositories.it_knowledge import (
    it_kb_categories,
    it_kb_get,
    it_kb_increment_usage,
    it_kb_list,
    it_kb_search,
    it_kb_upsert,
)
from repositories.logos import create_logo, list_logos
from repositories.memories import (
    clear_all_memories,
    create_memory,
    delete_memory,
    get_memories,
    update_memory,
)
from repositories.notes import (
    create_note,
    delete_note,
    get_note,
    list_notes,
    restore_note,
    update_note,
)
from repositories.operations import (
    ops_check_create,
    ops_check_delete,
    ops_check_get,
    ops_check_list,
    ops_check_update,
    ops_evidence_create,
    ops_evidence_list,
    ops_item_create,
    ops_result_set,
)
from repositories.network_inventory import (
    get_network_devices,
    register_network_device,
    set_network_device_notes,
    upsert_network_device,
)
from repositories.projects import (
    create_project,
    delete_project,
    get_project,
    get_projects,
    update_project,
)
from repositories.screenshots import create_screenshot, list_screenshots
from repositories.ssh_connections import (
    delete_ssh_connection,
    get_ssh_connection,
    find_ssh_connection,
    list_ssh_connections,
    save_ssh_connection,
    set_ssh_test_result,
    touch_ssh_connection,
    update_ssh_connection,
)
from repositories.settings import get_setting, set_setting
from repositories.system_snapshots import (
    get_system_snapshots,
    save_system_snapshot,
)
from repositories.tasks import (
    create_task,
    delete_task,
    get_task,
    list_tasks,
    update_task,
)
from repositories.tool_templates import (
    delete_template,
    get_template,
    list_templates,
    save_template,
)
from repositories.workflows import (
    create_workflow,
    create_workflow_run,
    delete_workflow,
    finish_workflow_run,
    get_workflow,
    list_workflow_runs,
    list_workflows,
    update_workflow,
)


initialize_database()
