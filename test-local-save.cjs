const fs=require('node:fs/promises'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const {ResourceFiles}= {ResourceFiles:require('./static/export-utils.js')};
class Directory {
 constructor(root){this.root=root;this.name=path.basename(root)}
 async getDirectoryHandle(name,{create=false}={}){const p=path.join(this.root,name);if(create)await fs.mkdir(p,{recursive:true});else await fs.access(p);return new Directory(p)}
 async getFileHandle(name,{create=false}={}){const p=path.join(this.root,name);if(create)await fs.writeFile(p,await fs.readFile(p).catch(()=>Buffer.alloc(0)));else await fs.access(p);return {getFile:async()=>new Blob([await fs.readFile(p)]),createWritable:async()=>{let chunks=[];const close=async()=>fs.writeFile(p,Buffer.concat(chunks));const stream=new WritableStream({write:chunk=>chunks.push(Buffer.from(chunk)),close});stream.write=async value=>chunks.push(Buffer.from(value));stream.close=close;return stream}}}
 async removeEntry(name){await fs.unlink(path.join(this.root,name))}
 async *entries(){for(const item of await fs.readdir(this.root,{withFileTypes:true})){if(item.isDirectory()){const h=await this.getDirectoryHandle(item.name);h.kind='directory';yield[item.name,h]}}}
}
(async()=>{
 const root=await fs.mkdtemp('/tmp/tingdu-local-save-');
 const record={id:'12345678123456781234567812345678',title:'本地资源',source:'upload',status:'done',text:'原始转写内容',summary:'核心要点',segments:[],media_file:'source.mp4',media_url:'/media',enhanced_url:'/enhanced',cover_url:'/cover',local_path:'/private/engine/data'};
 const dom=()=>({value:'',textContent:'',replaceChildren(){},classList:{toggle(){}},setAttribute(){},removeAttribute(){}});
 const sandbox={console,Blob,URL,TextEncoder,Response,WritableStream,ResourceFiles,document:{getElementById:()=>dom(),querySelectorAll:()=>[]},fetch:async url=>url==='/media'?new Response('original-video'):url==='/enhanced'?new Response('enhanced-audio'):url==='/cover'?new Response('cover-image'):new Response(JSON.stringify(record),{headers:{'content-type':'application/json'}})};
 const source=(await fs.readFile('static/app.js','utf8')).replace(/^const entryView=.*$/m,'');
 vm.createContext(sandbox);vm.runInContext(source+`\nrenderLibrary=()=>{};globalThis.test={saveOne,readDirectory,getRecord,resources,autoSave,selectVisible,selected:()=>[...checked],set:(dir,jobs)=>{directory=dir;engineJobs=jobs;localRecords.clear()},records:()=>[...localRecords.values()]};`,sandbox);
 const dir=new Directory(root);sandbox.test.set(dir,[record]);await sandbox.test.saveOne(record.id);
 const name=(await fs.readdir(root))[0],saved=JSON.parse(await fs.readFile(path.join(root,name,'record.json'),'utf8'));
 assert.equal(saved.summary,'核心要点');assert.equal(saved.enhanced_url,undefined);assert.equal(saved.saved_enhanced,'enhanced.wav');assert.equal(await fs.readFile(path.join(root,name,'enhanced.wav'),'utf8'),'enhanced-audio');assert.equal(saved.local_path,undefined);assert.equal(await fs.readFile(path.join(root,name,'media.mp4'),'utf8'),'original-video');assert.equal(await fs.readFile(path.join(root,name,'cover.jpg'),'utf8'),'cover-image');
 sandbox.test.set(dir,[]);await sandbox.test.readDirectory();const restored=await sandbox.test.getRecord(record.id);assert.equal(restored.text,'原始转写内容');assert.equal(restored.summary,'核心要点');assert.equal(restored._local,true);assert.equal(restored.saved_media,'media.mp4');
 const meeting={...record,id:'abcdefabcdefabcdefabcdefabcdefab',title:'录音记录',source:'meeting'};
 const meetingDir=await dir.getDirectoryHandle('旧录音',{create:true});
 await fs.writeFile(path.join(meetingDir.root,'record.json'),JSON.stringify(meeting));
 sandbox.test.set(dir,[record,meeting]);await sandbox.test.readDirectory();
 assert.deepEqual(Array.from(sandbox.test.resources(),r=>r.id),[record.id]);
 assert.equal(sandbox.test.records().some(r=>r.source==='meeting'),false);
 sandbox.test.selectVisible(true);assert.deepEqual(Array.from(sandbox.test.selected()),[record.id]);
 await assert.rejects(sandbox.test.getRecord(meeting.id),/录音转写/);
 await assert.rejects(sandbox.test.saveOne(meeting.id),/录音转写/);
 await sandbox.test.autoSave();
 assert.equal(await fs.readFile(path.join(meetingDir.root,'record.json'),'utf8'),JSON.stringify(meeting));
 assert.equal((await fs.readdir(root)).length,2,'自动保存不能新增录音副本');
 sandbox.test.set(dir,[meeting]);
 assert.equal(sandbox.test.resources().length,0,'只有录音时导入资源库为空');
 console.log('Recording isolation, selection, autosave and legacy folder preservation OK');
 console.log('Local directory save, original media, privacy metadata and offline restore OK');
})().catch(e=>{console.error(e);process.exitCode=1});
