-- Complete cross-entity foreign keys required by the governance model.

BEGIN;

ALTER TABLE continuity_snapshots
    ADD CONSTRAINT fk_continuity_snapshots_shot
        FOREIGN KEY (shot_id) REFERENCES shots(id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_continuity_snapshots_localization_release
        FOREIGN KEY (localization_release_id)
        REFERENCES localization_releases(id) ON DELETE SET NULL;

ALTER TABLE workflow_plans
    ADD CONSTRAINT fk_workflow_plans_model_release
        FOREIGN KEY (model_release_id) REFERENCES model_releases(id) ON DELETE SET NULL;

ALTER TABLE review_tasks
    ADD CONSTRAINT fk_review_tasks_assignee
        FOREIGN KEY (assignee_id) REFERENCES users(id) ON DELETE SET NULL,
    ADD CONSTRAINT fk_review_tasks_shot
        FOREIGN KEY (shot_id) REFERENCES shots(id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_review_tasks_episode
        FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE;

ALTER TABLE provenance_manifests
    ADD CONSTRAINT fk_provenance_manifests_delivery
        FOREIGN KEY (delivery_id) REFERENCES deliveries(id) ON DELETE SET NULL,
    ADD CONSTRAINT fk_provenance_manifests_episode
        FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE SET NULL;

ALTER TABLE provider_usage
    ADD CONSTRAINT fk_provider_usage_stage_attempt
        FOREIGN KEY (stage_attempt_id) REFERENCES stage_attempts(id) ON DELETE SET NULL;

ALTER TABLE cost_events
    ADD CONSTRAINT fk_cost_events_model_release
        FOREIGN KEY (model_release_id) REFERENCES model_releases(id) ON DELETE SET NULL;

COMMIT;
