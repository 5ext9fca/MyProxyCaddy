#!/usr/bin/env python3
"""从 .env / 进程环境生成公网 IPv4 配置；不执行 dotenv 中的代码。"""
import argparse
import ipaddress
import os
from pathlib import Path
import re
import shlex
import shutil
import tempfile
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
KEYS = ('PUBLIC_HOST', 'CADDY_NETWORK', 'CADDY_DATA_VOLUME', 'CADDY_CONFIG_VOLUME')
DEFAULTS = dict(zip(KEYS[1:], ('caddy-public', 'mycaddy_data', 'mycaddy_config')))


def read_env(path):
    values = {}
    if path.exists():
        for number, line in enumerate(path.read_text().splitlines(), 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('export '):
                line = line[7:].lstrip()
            key, sep, raw = line.partition('=')
            key = key.strip()
            if not sep or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
                raise ValueError(f'{path}:{number}: 应为 KEY=value')
            parts = shlex.split(raw, comments=True)
            if len(parts) > 1:
                raise ValueError(f'{path}:{number}: 含空格的值需要引号')
            values[key] = parts[0] if parts else ''
    return values


def configuration(path):
    values = {**DEFAULTS, **read_env(path)}
    values.update({key: os.environ[key] for key in KEYS if key in os.environ})
    host = values.get('PUBLIC_HOST', '')
    try:
        address = ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError:
        raise ValueError('PUBLIC_HOST 必须填写真实公网 IPv4，不带协议、端口或路径') from None
    if not address.is_global or address.is_multicast or address.is_reserved:
        raise ValueError('PUBLIC_HOST 必须是公网单播 IPv4，不能使用内网、回环或文档示例地址')
    for key in KEYS[1:]:
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*', values[key]):
            raise ValueError(f'{key} 只能包含字母、数字、下划线、点和连字符，且以字母或数字开头')
    return values


def write(path, content, dry_run):
    if path.exists() and path.read_text() == content:
        print(f'未变化：{path}')
        return
    print(f'{"将生成" if dry_run else "生成"}：{path}')
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(path.name + '.bak.' + datetime.now().strftime('%Y%m%d%H%M%S%f'))
        shutil.copy2(path, backup)
        print(f'已备份：{backup}')
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
    try:
        temporary.chmod(0o644)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--output-dir', type=Path, default=ROOT,
                        help='生成目录；默认项目根目录，可指定临时目录预览')
    parser.add_argument('--dry-run', action='store_true', help='校验并显示待写文件，不修改文件')
    args = parser.parse_args()
    try:
        values = configuration(args.env_file)
        host = values['PUBLIC_HOST']
        template = (ROOT / 'templates/Caddyfile.template').read_text()
        caddyfile = '# 由 scripts/configure.py 生成；修改站点结构请编辑 templates/Caddyfile.template。\n' + template.replace('{$PUBLIC_HOST}', host)
        files = {
            'conf/Caddyfile': caddyfile,
            'generated/mycaddy.env': ''.join(f'{key}={values[key]}\n' for key in KEYS),
            'generated/mycollab.env': f'CADDY_NETWORK={values["CADDY_NETWORK"]}\nDJANGO_ALLOWED_HOSTS={host}\nDJANGO_CSRF_TRUSTED_ORIGINS=https://{host}\n',
            'generated/clash.env': f'CADDY_NETWORK={values["CADDY_NETWORK"]}\n',
        }
        for relative, content in files.items():
            write(args.output_dir / relative, content, args.dry_run)
        print('完成。业务环境片段需合并到对应 .env，保留原密钥；脚本不会启动或重载服务。')
    except (ValueError, OSError) as error:
        parser.exit(1, f'配置失败：{error}\n')


if __name__ == '__main__':
    main()
