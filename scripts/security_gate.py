#!/usr/bin/env python3
"""Evaluate an unfiltered Trivy report with exact, expiring OS-package reviews."""
import argparse
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

FIELDS = {'id','package','versions','os_family','os_major','status','reason','references','reviewed_at','expires_at','reviewed_by'}
SEVERITIES = {'UNKNOWN','LOW','MEDIUM','HIGH','CRITICAL'}

def validate_reviews(policy):
    if not isinstance(policy, dict) or set(policy) != {'schema','reviews'} or type(policy['schema']) is not int or policy['schema'] != 1 or not isinstance(policy['reviews'], list):
        raise ValueError('Invalid review policy schema')
    scopes = set()
    for r in policy['reviews']:
        if not isinstance(r, dict) or set(r) != FIELDS:
            raise ValueError('Review fields are missing or unknown')
        if any(not isinstance(r[k], str) or not r[k].strip() for k in FIELDS - {'versions','references'}):
            raise ValueError('Review strings must be nonempty')
        if not re.fullmatch(r'CVE-\d{4}-\d{4,}', r['id']) or not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*', r['package']):
            raise ValueError('Invalid CVE or package')
        if r['status'] not in {'not_affected','vendor_minor_deferred'}:
            raise ValueError('Invalid review status')
        if not isinstance(r['versions'], list) or not r['versions'] or any(not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9.+:~_-]+', v) for v in r['versions']):
            raise ValueError('Exact package versions are required')
        if not isinstance(r['references'], list) or not r['references'] or any(not isinstance(v,str) or not v.startswith('https://') for v in r['references']):
            raise ValueError('HTTPS review references are required')
        start, end = date.fromisoformat(r['reviewed_at']), date.fromisoformat(r['expires_at'])
        if not 0 < (end-start).days <= 7:
            raise ValueError('Review must expire within seven days')
        if r['os_family'] != 'debian' or not re.fullmatch(r'\d+',r['os_major']):
            raise ValueError('Review must identify a Debian major release')
        for version in r['versions']:
            scope = (r['id'],r['package'],version,r['os_family'],r['os_major'])
            if scope in scopes: raise ValueError('Duplicate review scope')
            scopes.add(scope)
    return policy['reviews']

def evaluate(report, policy, today=None):
    today = today or datetime.now(timezone.utc).date()
    reviews = validate_reviews(policy)
    if not isinstance(report,dict) or not isinstance(report.get('Results'),list):
        raise ValueError('Trivy Results list missing')
    metadata = report.get('Metadata')
    if not isinstance(metadata,dict) or not isinstance(metadata.get('OS'),dict):
        raise ValueError('Trivy OS metadata missing')
    osinfo = metadata['OS']
    if not isinstance(osinfo.get('Family'),str) or not isinstance(osinfo.get('Name'),str) or not osinfo['Family'] or not osinfo['Name']:
        raise ValueError('Trivy OS metadata missing')
    counts = Counter()
    blocking, reviewed = [], []
    for result in report['Results']:
        if not isinstance(result,dict): raise ValueError('Invalid Trivy result')
        findings = result.get('Vulnerabilities')
        if findings is None: findings = []
        if not isinstance(findings,list): raise ValueError('Invalid findings list')
        for v in findings:
            if not isinstance(v,dict) or any(not isinstance(v.get(k),str) or not v[k] for k in ['VulnerabilityID','PkgName','InstalledVersion','Severity']) or v['Severity'] not in SEVERITIES:
                raise ValueError('Malformed vulnerability record')
            counts[v['Severity']] += 1
            if v['Severity'] != 'CRITICAL': continue
            match = None
            # A newly available fix always removes the deferral, even before expiry.
            if result.get('Class') == 'os-pkgs' and not v.get('FixedVersion'):
                for r in reviews:
                    if (r['id'] == v['VulnerabilityID'] and r['package'] == v['PkgName']
                            and v['InstalledVersion'] in r['versions'] and r['os_family'] == osinfo['Family']
                            and r['os_major'] == osinfo['Name'].split('.')[0]
                            and date.fromisoformat(r['reviewed_at']) <= today < date.fromisoformat(r['expires_at'])):
                        match = r
                        break
            finding = {k:v.get(k,'') for k in ['VulnerabilityID','PkgName','InstalledVersion','FixedVersion','Severity']}
            finding['target'] = result.get('Target','')
            if match: reviewed.append({'finding':finding,'review':match})
            else: blocking.append(finding)
    return {'date_utc':today.isoformat(),'image':report.get('ArtifactName',''), 'severity_counts':dict(counts),
            'reviewed_critical':reviewed,'blocking_critical':blocking,'passed':not blocking}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path)
    parser.add_argument('--reviews',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args = parser.parse_args()
    raw = args.report.read_bytes()
    summary = evaluate(json.loads(raw),json.loads(args.reviews.read_text()))
    summary['report_sha256'] = hashlib.sha256(raw).hexdigest()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temp = args.output.with_suffix('.tmp')
    temp.write_text(json.dumps(summary,indent=2)+'\n')
    temp.replace(args.output)
    print(f"Security gate: {len(summary['blocking_critical'])} blocking, {len(summary['reviewed_critical'])} explicitly reviewed CRITICAL findings")
    return 0 if summary['passed'] else 1

if __name__ == '__main__':
    try: sys.exit(main())
    except (ValueError,KeyError,TypeError,OSError) as exc:
        print('Security gate invalid input: '+str(exc),file=sys.stderr)
        sys.exit(2)
