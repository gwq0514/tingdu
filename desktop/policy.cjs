const ORIGIN='http://127.0.0.1:18765';
function localOrigin(url){try{return new URL(url).origin===ORIGIN}catch{return false}}
function allowedPermission(permission,details={}){
 if(permission==='media')return details.mediaTypes?.length>0&&details.mediaTypes.every(t=>t==='audio');
 return ['clipboard-sanitized-write','fileSystem'].includes(permission);
}
module.exports={ORIGIN,localOrigin,allowedPermission};
