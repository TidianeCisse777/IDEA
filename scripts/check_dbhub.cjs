// Real stdio MCP handshake and reader query, without printing credentials.
const {spawn}=require('node:child_process');
const path=require('node:path');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const child=spawn('powershell.exe',['-NoProfile','-ExecutionPolicy','Bypass','-File',path.join(__dirname,'start_dbhub.ps1')],{cwd:root,windowsHide:true,stdio:['pipe','pipe','pipe']});
let buffer='',nextId=0;
const pending=new Map();
child.stderr.on('data',()=>{}); // Server logs can contain connection diagnostics.
child.stdout.on('data',chunk=>{
  buffer+=chunk.toString();
  let newline;
  while((newline=buffer.indexOf('\n'))>=0){
    const line=buffer.slice(0,newline);buffer=buffer.slice(newline+1);
    try {const message=JSON.parse(line),entry=pending.get(message.id);if(entry){pending.delete(message.id);message.error?entry.reject(new Error('Erreur RPC DbHub')):entry.resolve(message.result)}} catch {}
  }
});
function rpc(method,params){return new Promise((resolve,reject)=>{const id=++nextId;pending.set(id,{resolve,reject});child.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n')})}
const timeout=setTimeout(()=>{child.kill();console.error('FAIL : délai MCP dépassé');process.exit(1)},45000);
(async()=>{
  await rpc('initialize',{protocolVersion:'2025-03-26',capabilities:{},clientInfo:{name:'neolab-check',version:'1'}});
  child.stdin.write(JSON.stringify({jsonrpc:'2.0',method:'notifications/initialized'})+'\n');
  const list=await rpc('tools/list',{});
  const tool=list.tools.find(tool=>tool.name==='execute_sql');assert.ok(tool);
  const contextTool=list.tools.find(tool=>tool.name==='warehouse_context');assert.ok(contextTool);
  assert.match(contextTool.description,/overview/);
  const context=await rpc('tools/call',{name:contextTool.name,arguments:{topic:'overview'}});
  assert.ok(!context.isError);assert.match(JSON.stringify(context),/annotation|dénominateurs/);
  const graphContext=await rpc('tools/call',{name:contextTool.name,arguments:{topic:'graphs'}});
  assert.ok(!graphContext.isError);assert.match(JSON.stringify(graphContext),/Matplotlib/);
  assert.match(JSON.stringify(graphContext),/Exploratoire/);
  assert.match(JSON.stringify(graphContext),/CSV/);
  for(const library of ['Cartopy','Folium','oceans','TEOS-10','cmocean'])assert.ok(JSON.stringify(graphContext).includes(library));
  const sampleContext=await rpc('tools/call',{name:contextTool.name,arguments:{topic:'filet_ctd'}});
  assert.ok(!sampleContext.isError);assert.match(JSON.stringify(sampleContext),/NATIF/);
  const dictionary=await rpc('tools/call',{name:tool.name,arguments:{sql:"SELECT column_description,view_description,sql_definition FROM explore.warehouse_dictionary WHERE view_name='uvp_taxon_abundance' AND column_name='sampled_volume_l'"}});
  assert.ok(!dictionary.isError);assert.match(JSON.stringify(dictionary),/litres/);
  const discovery=list.tools.find(tool=>tool.name==='search_objects');assert.ok(discovery);
  const schema=await rpc('tools/call',{name:discovery.name,arguments:{object_type:'column',schema:'explore',table:'uvp_taxon_abundance',pattern:'sampled_volume_l',detail_level:'full'}});
  assert.ok(!schema.isError);assert.match(JSON.stringify(schema),/litres/);
  const result=await rpc('tools/call',{name:tool.name,arguments:{sql:'SELECT current_user AS role, current_setting(\'transaction_read_only\') AS read_only, count(*) AS datasets FROM explore.uvp_projects'}});
  assert.ok(!result.isError,'La requête lecteur doit réussir');
  assert.match(JSON.stringify(result),/warehouse_reader/);
  console.log('PASS : MCP, contexte métier, dictionnaire, commentaires de découverte et SQL lecteur.');
})().catch(()=>{console.error('FAIL : recette MCP/SQL');process.exitCode=1}).finally(()=>{clearTimeout(timeout);child.kill()});
