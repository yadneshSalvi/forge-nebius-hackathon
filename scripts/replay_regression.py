"""Post-final reproduction of an observed non-nominated regression, without training."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import run_episode
from control.store import Store, Conflict, canonical, digest, now


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--campaign', required=True)
    parser.add_argument('--seed', type=int, default=404)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    store = Store()
    parent = store.get(args.campaign, detail=False)
    report = parent['registered_report']
    final = store.get(report['evaluation_campaign_id'], detail=False)
    if final['status'] != 'completed' or report['nominations']['minimized']['seed'] == args.seed:
        raise ValueError('Requires completed final evaluation and a non-nominated seed')
    rows = store.read_artifact(report['outcomes_sha'])['rows']
    bases = {r['scenario_id']: r for r in rows if r['arm'] == 'base'}
    eligible = [r for r in rows if r['arm'] == 'minimized' and r['training_seed'] == args.seed and bases[r['scenario_id']]['success'] and not r['success']]
    if not eligible:
        raise ValueError('No registered base-to-revised regression for this seed')
    target = sorted(eligible, key=lambda r: r['scenario_id'])[0]
    scenario = store.episode(target['episode_id'])['scenario']
    policies = [store.read_artifact(parent['config']['base_checkpoint_sha']), store.read_artifact(target['checkpoint_sha'])]
    started_at = now()
    episodes = [run_episode(scenario, p, trace=True) for p in policies]
    for episode, original in zip(episodes, [bases[target['scenario_id']], target]):
        if episode['status'] != 'completed' or any(episode[k] != original[k] for k in ('success', 'terminal_reason', 'metrics')):
            raise ValueError('Fresh diagnostic physics differs from the registered outcome')
    config = {'kind': 'challenge', 'scope': 'post_final_reproduction_non_nominated', 'search_budget': 2, 'seed': scenario['seed'], 'live_models': False, 'parent_campaign_id': parent['id'], 'evaluation_campaign_id': final['id'], 'task_sha': parent['config']['task_sha'], 'protocol_sha': parent['config']['protocol_sha'], 'source_sha': parent['config']['source_sha'], 'base_checkpoint_sha': parent['config']['base_checkpoint_sha'], 'revised_checkpoint_sha': target['checkpoint_sha'], 'training_seed': args.seed, 'challenge_scenario': scenario, 'registered_manifest_sha': report['manifest_sha']}
    # Physics needs no local worker slot. Wait to commit if an interactive run
    # currently owns it; never interrupt that run or alter its outcomes.
    deadline = time.monotonic() + 60
    while True:
        try:
            cid, created = store.create(f'Post-final reproduction · non-nominated seed {args.seed}', config, 'postfinal-' + digest(config)[:40])
            break
        except Conflict:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.2)
    if created:
        info = store.launch_info(cid)
        store.claim(cid, 1, info['worker_token'], os.getpid())
        ids, hashes = [], []
        for role, episode, policy in zip(('base', 'revised'), episodes, policies):
            ident = f'{cid}-{role}'
            summary = {'id': ident, 'engine_episode_id': episode['episode_id'], 'scenario': scenario, 'policy_id': policy['policy_id'], 'checkpoint_hash': policy['checkpoint_hash'], 'purpose': 'post_final_reproduction', 'success': episode['success'], 'valid': True, 'outcome': episode['terminal_reason'], 'terminal_reason': episode['terminal_reason'], 'status': 'completed', 'metrics': episode['metrics'], 'trace_available': True}
            store.save_episode(cid, 1, role, episode, summary)
            ids.append(ident)
            hashes.append(store.artifact(episode))
        receipt = {'schema': 'forge.post-final-reproduction/v1', 'campaign_id': cid, 'source_campaign_id': parent['id'], 'evaluation_campaign_id': final['id'], 'label': f'Non-nominated seed {args.seed} · post-final reproduction', 'scope': 'Verification of an observed frozen-checkpoint regression; excluded from registered statistics and nomination.', 'retraining': False, 'nominated': False, 'arm': 'minimized', 'training_seed': args.seed, 'checkpoint_sha': target['checkpoint_sha'], 'checkpoint_hash': policies[1]['checkpoint_hash'], 'scenario_id': target['scenario_id'], 'scenario': scenario, 'base_episode_id': ids[0], 'revised_episode_id': ids[1], 'base_artifact_sha': hashes[0], 'revised_artifact_sha': hashes[1], 'base_success': True, 'revised_success': False, 'base_reason': episodes[0]['terminal_reason'], 'revised_reason': episodes[1]['terminal_reason'], 'reproduction_started_at': started_at, 'reproduction_finished_at': now(), 'original_base_episode_id': bases[target['scenario_id']]['episode_id'], 'original_revised_episode_id': target['episode_id'], 'registered_report_sha': report['artifact_sha'], 'registered_manifest_sha': report['manifest_sha']}
        receipt['evidence_sha'] = store.artifact(receipt)
        store.finish(cid, 1, 'completed', 'reproduction', {'supplementary_reproduction': receipt})
        with store.transaction() as connection:
            row = connection.execute('SELECT payload FROM campaigns WHERE id=?', (parent['id'],)).fetchone()
            payload = json.loads(row['payload'])
            if payload['registered_report']['artifact_sha'] != report['artifact_sha']:
                raise ValueError('Registered report changed during diagnostic attachment')
            retained = payload.get('supplementary_reproductions', [])
            payload['supplementary_reproductions'] = [r for r in retained if r['campaign_id'] != cid] + [receipt]
            connection.execute('UPDATE campaigns SET payload=? WHERE id=?', (canonical(payload).decode(), parent['id']))
            store._event(connection, parent['id'], parent['generation'], 'supplementary_reproduction_attached', {'campaign_id': cid, 'evidence_sha': receipt['evidence_sha'], 'registered_report_unchanged': True})
    else:
        receipt = store.get(cid, detail=False)['supplementary_reproduction']
        # The new verification above already matched the outcome. Preserve
        # the original recording's exact bytes/hash for idempotent exports.
        episodes = [store.read_artifact(receipt[key]) for key in ('base_artifact_sha', 'revised_artifact_sha')]
    args.output.mkdir(parents=True, exist_ok=True)
    for name, episode in zip(('base', 'revised'), episodes):
        (args.output / f'{name}.json').write_bytes(canonical(episode))
    (args.output / 'receipt.json').write_bytes(canonical(receipt))
    print(json.dumps({'campaign_id': cid, 'receipt': receipt, 'raw_directory': str(args.output.resolve())}, indent=2))


if __name__ == '__main__':
    main()
