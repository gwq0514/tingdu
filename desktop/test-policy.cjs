const assert=require('node:assert/strict');const {localOrigin,allowedPermission}=require('./policy.cjs');
assert(localOrigin('http://127.0.0.1:18765/meetings?embedded=1'));
for(const u of ['https://example.com','http://127.0.0.1:8765','http://127.0.0.1:18765.evil.test','file:///etc/passwd'])assert(!localOrigin(u));
assert(allowedPermission('media',{mediaTypes:['audio']}));
assert(!allowedPermission('media',{mediaTypes:['video']}));assert(!allowedPermission('media',{mediaTypes:['audio','video']}));assert(!allowedPermission('media'));
assert(allowedPermission('fileSystem'));assert(!allowedPermission('display-capture'));assert(!allowedPermission('geolocation'));
console.log('Desktop permissions: local audio only; camera, screen and remote pages denied.');
