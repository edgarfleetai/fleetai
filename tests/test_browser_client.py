"""Exercise the actual browser CSRF fetch shim with Node's Request runtime."""
import shutil
import subprocess
import pytest


def test_csrf_client_wraps_existing_fetch_without_cross_origin_leak():
    from fleetai.security_policy import CLIENT_JS
    node = shutil.which('node')
    if node is None:
        pytest.fail('Node is required to verify the shipped browser fetch shim')
    harness = r'''
const assert = require('node:assert/strict');
const NativeRequest = global.Request;
global.location = {href:'https://fleetai.test/driver?code=700',origin:'https://fleetai.test'};
global.Request = class extends NativeRequest {
 constructor(input, options) {super(typeof input === 'string' ? new URL(input,location.href) : input,options);}
};
const calls=[];
global.window={fetch:async (input,opts)=>{
 if (input==='/auth/session') {
  assert.equal(opts.credentials,'same-origin');
  return {ok:true,json:async()=>({kind:'owner',csrf_token:'synthetic-csrf'})};
 }
 calls.push(input);
 return {ok:true,status:200};
}};
'''
    trailer = r'''
(async()=>{
 await window.fetch('/api/cars');
 await window.fetch('/api/driver-wallet/topup',{method:'POST',headers:{'Content-Type':'application/json'},body:'{"amount":1}'});
 await window.fetch('https://outside.invalid/api/cars');
 assert.equal(calls[0].headers.get('X-CSRF-Token'),'synthetic-csrf');
 assert.equal(calls[1].headers.get('X-CSRF-Token'),'synthetic-csrf');
 assert.equal(calls[1].headers.get('Content-Type'),'application/json');
 assert.equal(await calls[1].text(),'{"amount":1}');
 assert.equal(calls[2].headers.get('X-CSRF-Token'),null);
 console.log('fetch shim: same-origin GET/POST protected, JSON preserved, cross-origin secret not attached');
})().catch(e=>{console.error(e.message);process.exitCode=1});
'''
    result = subprocess.run([node], input=harness + CLIENT_JS + trailer, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert 'cross-origin secret not attached' in result.stdout
