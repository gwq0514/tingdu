const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const {safeName,entries,buildZip}=require('./static/export-utils.js');
(async()=>{
const resources=[{id:'aaaaaaaa111111111111111111111111',title:'同名/中文视频',source:'upload',text:'完整原文一',summary:'关键观点',segments:[]},{id:'bbbbbbbb111111111111111111111111',title:'同名/中文视频',source:'text',text:'完整原文二',segments:[{start:61.5,text:'带时间戳的文字'}]}];
const files=entries(resources);assert.notEqual(files[0].name,files[1].name);assert.ok(files[0].data.includes('关键观点'));assert.ok(files[1].data.includes('[00:01:01]'));assert.equal(safeName('../资源:*?'),'.._资源___');
const zip=buildZip(files);await fs.writeFile('/tmp/tingdu-export-test.zip',new Uint8Array(await zip.arrayBuffer()));
console.log('ZIP generation OK');
})();
