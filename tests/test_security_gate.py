import copy
from datetime import date
import importlib.util
import json
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('gate',Path(__file__).resolve().parents[1]/'scripts/security_gate.py')
gate=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

class SecurityGateTests(unittest.TestCase):
    def test_brotli_review_covers_only_fixed_upstream_package(self):
        policy = json.loads((Path(__file__).resolve().parents[1] / 'security/reviews.json').read_text())
        for version, expected in [('1.1.0-2+b7', False), ('1.1.1-0+tgi1', True), ('1.1.1-0+tgi2', False)]:
            report = {'Metadata': {'OS': {'Family': 'debian', 'Name': '13'}}, 'Results': [
                {'Class': 'os-pkgs', 'Vulnerabilities': [{'VulnerabilityID': 'CVE-2026-111497',
                 'PkgName': 'libbrotli1', 'InstalledVersion': version, 'Severity': 'CRITICAL'}]}]}
            with self.subTest(version=version):
                self.assertEqual(gate.evaluate(report, policy, date(2026, 10, 23))['passed'], expected)

    def setUp(self):
        self.policy={'schema':1,'reviews':[{'id':'CVE-2026-6653','package':'libxml2','versions':['1.0'],
            'os_family':'debian','os_major':'13','status':'vendor_minor_deferred','reason':'Vendor minor issue reviewed',
            'references':['https://security-tracker.debian.org/tracker/CVE-2026-6653'],
            'reviewed_at':'2026-10-22','expires_at':'2026-10-29','reviewed_by':'Automated review'}]}
        self.report={'Metadata':{'OS':{'Family':'debian','Name':'13.7'}},'Results':[
            {'Class':'os-pkgs','Vulnerabilities':[{'VulnerabilityID':'CVE-2026-6653','PkgName':'libxml2',
            'InstalledVersion':'1.0','Severity':'CRITICAL'}]}]}
        self.today=date(2026,10,22)
    def evaluate(self): return gate.evaluate(self.report,self.policy,self.today)
    def test_review_is_preserved_and_not_hidden(self):
        result=self.evaluate()
        self.assertTrue(result['passed'])
        self.assertEqual(1,result['severity_counts']['CRITICAL'])
        self.assertEqual(self.policy['reviews'][0],result['reviewed_critical'][0]['review'])
    def test_new_critical_blocks(self):
        self.report['Results'][0]['Vulnerabilities'][0]['VulnerabilityID']='CVE-2026-9999'
        self.assertFalse(self.evaluate()['passed'])
    def test_expiry_and_future_fail_closed(self):
        for day in [date(2026,10,21),date(2026,10,29)]:
            self.assertFalse(gate.evaluate(self.report,self.policy,day)['passed'])
    def test_version_drift_blocks(self):
        self.report['Results'][0]['Vulnerabilities'][0]['InstalledVersion']='1.1'
        self.assertFalse(self.evaluate()['passed'])
    def test_new_fix_blocks_before_expiry(self):
        self.report['Results'][0]['Vulnerabilities'][0]['FixedVersion']='1.1'
        self.assertFalse(self.evaluate()['passed'])
    def test_distro_drift_blocks(self):
        self.report['Metadata']['OS']['Name']='14'
        self.assertFalse(self.evaluate()['passed'])
    def test_language_package_cannot_use_os_review(self):
        self.report['Results'][0]['Class']='lang-pkgs'
        self.assertFalse(self.evaluate()['passed'])
    def test_unknown_fields_and_unbounded_reviews_rejected(self):
        base=copy.deepcopy(self.policy)
        for mutation in [{'expire_at':'2026-10-29'},{'expires_at':'2026-11-22'},{'versions':['*']}]:
            self.policy=copy.deepcopy(base)
            self.policy['reviews'][0].update(mutation)
            with self.assertRaises(ValueError): self.evaluate()
    def test_duplicate_scope_rejected(self):
        self.policy['reviews'].append(copy.deepcopy(self.policy['reviews'][0]))
        with self.assertRaises(ValueError): self.evaluate()
    def test_invalid_or_missing_report_rejected(self):
        for report in [{},{'Results':[]},{'Results':'not-list','Metadata':self.report['Metadata']}]:
            with self.assertRaises(ValueError): gate.evaluate(report,self.policy,self.today)

if __name__=='__main__': unittest.main()
