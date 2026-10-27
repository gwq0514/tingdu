// Local integrity signature only; this is not Apple Developer ID signing or notarization.
const {spawnSync}=require('node:child_process');const path=require('node:path');
module.exports=async context=>{
 if(context.electronPlatformName!=='darwin')return;
 const appPath=path.join(context.appOutDir,context.packager.appInfo.productFilename+'.app');
 const r=spawnSync('/usr/bin/codesign',['--force','--deep','--sign','-','--identifier','online.tingdu.desktop',appPath],{encoding:'utf8'});
 if(r.status!==0)throw Error(r.stderr);
};
