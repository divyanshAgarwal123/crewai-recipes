"""Offline workflow smoke test. Does not call a provider."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import types
import yaml

if len(sys.argv) > 1 and sys.argv[1] == '--execute-cli':
    sys.argv = sys.argv[2:]
    def build_crew(**inputs):
        Path(os.environ['FIXTURE_CALL_PATH']).write_text(json.dumps(inputs))
        class FixtureCrew:
            def kickoff(self):
                if os.environ.get('FIXTURE_FAIL') == '1':
                    raise RuntimeError('Intentional fixture provider failure')
                return 'OFFLINE FIXTURE: article output, not provider-generated content.'
        return FixtureCrew()
    sys.modules['crew'] = types.SimpleNamespace(build_crew=build_crew)
    runpy.run_path(sys.argv[0], run_name='__main__')
    raise SystemExit

root = Path.cwd()
workflow = root / 'examples/github-actions/nightly-content-workflow.yml'
y = yaml.load(workflow.read_text(), Loader=yaml.BaseLoader)
assert y['on']['schedule'][0]['cron'] == '0 8 * * *'
steps = y['jobs']['content']['steps']
step = next(s for s in steps if s.get('name') == 'Run fixed-input recipe')
assert step['env']['LLM_API_KEY'] == '${{ secrets.LLM_API_KEY }}'
assert y['permissions'] == {'contents': 'read'}
assert 'cache: pip' in workflow.read_text()
assert workflow.read_text() in (root / 'docs/integrations/github-action.md').read_text()
script = Path(__file__).resolve()
results = []
with tempfile.TemporaryDirectory(prefix='crew188-') as temp:
    temp = Path(temp)
    (temp/'bin').mkdir()
    shim = temp/'bin/python'
    import shlex
    shim.write_text('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' '+shlex.quote(str(script))+' --execute-cli "$@"\n')
    # Strip -u while keeping exactly the recipe's argv.
    shim.write_text(shim.read_text().replace('--execute-cli "$@"', '--execute-cli "${@:2}"').replace('#!/bin/sh', '#!/bin/bash'))
    shim.chmod(0o755)
    for name, key, fail in [('missing-secret', '', ''), ('fixed-input-success', 'offline-placeholder', ''), ('recipe-failure', 'offline-placeholder', '1')]:
        target=temp/name;target.mkdir()
        env={**os.environ, 'PATH':str(temp/'bin')+os.pathsep+os.environ['PATH'], 'GITHUB_WORKSPACE':str(target), 'LLM_API_KEY':key, 'FIXTURE_FAIL':fail, 'FIXTURE_CALL_PATH':str(target/'call.json')}
        result=subprocess.run(['bash','--noprofile','--norc','-e','-o','pipefail','-c',step['run']],cwd=root/step['working-directory'],env=env,capture_output=True,text=True)
        assert (result.returncode == 0) == (name == 'fixed-input-success'), (name,result.stderr,result.stdout)
        if name == 'missing-secret':
            assert not (target/'call.json').exists()
            assert 'Add the LLM_API_KEY repository secret' in result.stdout
        if name == 'fixed-input-success':
            assert json.loads((target/'call.json').read_text()) == {'topic':'A practical guide to reviewing pull requests','target_audience':'Open source maintainers','keywords':'pull requests, code review, collaboration'}
            assert 'OFFLINE FIXTURE' in (target/'artifacts/content.txt').read_text()
            (root/'artifacts').mkdir(exist_ok=True)
            (root/'artifacts/content.txt').write_bytes((target/'artifacts/content.txt').read_bytes())
        results.append({'case':name,'exitCode':result.returncode,'pass':True})
print(json.dumps({'validation':'offline fixture only; no provider call','cases':results},indent=2))
