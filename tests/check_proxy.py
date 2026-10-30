import os
import subprocess
import tempfile
import pathlib
import shutil
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEPLOY = pathlib.Path(os.environ.get("MYCOLLAB_DEPLOY", str(ROOT.parent / "MyCollabAdvanced/deploy")))

def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT)

base=pathlib.Path(tempfile.mkdtemp(prefix='mycaddy-test-'))
network='mycaddy-test-'+str(os.getpid())
names=[]
try:
    shutil.copytree(ROOT / 'conf',base/'edge')
    p=base/'edge/Caddyfile'; s=p.read_text()
    # 同时支持原始环境变量模板和生成后的固定公网 IP。
    host = s.split('default_sni ', 1)[1].splitlines()[0].strip()
    s = s.replace(host, 'localhost')
    start=s.index('\ttls {'); end=s.index('\tencode gzip',start); p.write_text(s[:start]+'\ttls internal\n'+s[end:])
    shutil.copy(DEPLOY / 'Caddyfile',base/'Webfile')
    (base/'Mockfile').write_text(':8000 {\n respond "{http.request.header.X-Forwarded-Proto}|{uri}"\n}\n:8080 {\n respond "subscription:{uri}" 404\n}\n')
    (base/'srv/frontend').mkdir(parents=True); (base/'srv/static').mkdir()
    (base/'srv/frontend/index.html').write_text('SPA_OK')
    (base/'srv/static/test.txt').write_text('STATIC_OK')
    run('docker','network','create',network)
    def start(label,alias,config,extra=()):
        name=network+'-'+label; names.append(name)
        run('docker','run','-d','--name',name,'--network',network,'--network-alias',alias,*extra,'-v',f'{config}:/etc/caddy/Caddyfile:ro','caddy:2.11.7-alpine')
        return name
    mock=start('mock','backend',base/'Mockfile',('--network-alias','clash-subscription'))
    web=start('web','mycollab-web',base/'Webfile',('-v',f'{base}/srv:/srv:ro'))
    edge=start('edge','edge',base/'edge/Caddyfile',('-p','127.0.0.1::443','-e','PUBLIC_HOST=localhost','-v',f'{base}/edge/routes:/etc/caddy/routes:ro'))
    time.sleep(2)
    run('docker','cp',edge+':/data/caddy/pki/authorities/local/root.crt',str(base/'root.crt'))
    port=run('docker','port',edge,'443/tcp').strip().rsplit(':',1)[1]
    for path,expected,status in [('/','SPA_OK','200'),('/missions/123','SPA_OK','200'),('/static/test.txt','STATIC_OK','200'),('/api/test','https|/api/test','200'),('/admin/test','https|/admin/test','200'),('/sub/invalid/config.yaml','subscription:/sub/invalid/config.yaml','404'),('/sub','subscription:/sub','404')]:
        output=run('curl','--silent','--show-error','--max-time','10','--cacert',str(base/'root.crt'),'--resolve',f'localhost:{port}:127.0.0.1','-w','|%{http_code}',f'https://localhost:{port}{path}')
        assert output==expected+'|'+status,(path,output)
        print('PASS',path)

finally:
    for name in reversed(names):
        subprocess.run(['docker','rm','-fv',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    subprocess.run(['docker','network','rm',network],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    shutil.rmtree(base)
