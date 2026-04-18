#!/usr/bin/env python3
import yaml

with open('/home/suchokrates1/traefik/dynamic/minipc_services.yml') as f:
    cfg = yaml.safe_load(f)

cfg['http']['routers']['minipc-check'] = {
    'rule': 'Host(`minipc-check.retrievershop.pl`)',
    'service': 'magazyn2',
    'entryPoints': ['https'],
    'tls': {'certResolver': 'cloudflare'},
    'middlewares': ['secure-headers'],
}

with open('/home/suchokrates1/traefik/dynamic/minipc_services.yml', 'w') as f:
    yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)

print('Dodano router minipc-check -> magazyn2')
