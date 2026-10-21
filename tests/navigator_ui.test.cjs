// Deterministic UI logic contracts, without network or a browser.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../warehouse_navigator/static/index.html'),'utf8');
const script=html.split('<script>')[1].split('</script>')[0].split("['uvp','filet'].forEach")[0];
function setup(){
  const elements=new Map(),drawn=[];
  const element=id=>{if(!elements.has(id))elements.set(id,{textContent:'',value:'',checked:false,hidden:false,attributes:{},setAttribute(name,value){this.attributes[name]=String(value)},removeAttribute(name){delete this.attributes[name]}});return elements.get(id)};
  const map={setView(){return this},removeLayer(){},getZoom(){return 3}};
  const layer=()=>({addTo(){return this},bindPopup(){return this},on(){return this}});
  const context=vm.createContext({Intl,URLSearchParams,console:{error(){}},document:{getElementById:element,querySelectorAll:()=>[]},L:{map:()=>map,tileLayer:layer,layerGroup:layer,circleMarker:(coords,options)=>{drawn.push({coords,options});return layer()},polyline:layer}});
  vm.runInContext(script,context);
  return {context,element,drawn,run:code=>vm.runInContext(code,context)};
}
const coverage={filters:{zones:[]},uvp:{profiles:5,geolocated_profiles:4,objects_mapped:12,first_date:'2020-01-01',last_date:'2024-01-01'},ctd:{profiles:2},filet:{samples:9,first_date:'2010-01-01',last_date:'2025-01-01'}};
test('spatial threshold reaches all three comparison endpoints, including zero',async()=>{
  const s=setup(),urls=[];s.element('matches').checked=true;s.element('hours').value='10';s.element('distanceKm').value='0';
  s.context.fetch=async url=>{urls.push(url);return {ok:true,json:async()=>url.includes('/coverage')?coverage:url.includes('/map')?{uvp:[],filet:[]}:{matches:[]}}};
  await s.run('load()');
  assert.equal(urls.length,3);
  urls.forEach(url=>assert.equal(new URL(url,'http://localhost').searchParams.get('max_distance_km'),'0'));
});
test('summary follows the visible sources and combines their periods',()=>{
  const s=setup();s.context.fixture=coverage;s.run('coverageData=fixture');
  s.element('uvp').checked=true;s.element('filet').checked=true;s.run('renderSummary()');
  assert.equal(s.element('period').textContent,'2010-01-01 → 2025-01-01');
  assert.equal(s.element('unmapped').textContent,'1 sans coordonnées');
  s.element('filet').checked=false;s.run('renderSummary()');
  assert.equal(s.element('filets').textContent,'0');assert.equal(s.element('period').textContent,'2020-01-01 → 2024-01-01');
  s.element('uvp').checked=false;s.run('renderSummary()');
  for(const id of ['profiles','objects','ctds','filets'])assert.equal(s.element(id).textContent,'0');
  assert.equal(s.element('period').textContent,'Aucune donnée dans la sélection');
});
test('dates without timezone stay UTC and gap rounding is explicit',()=>{
  const s=setup();assert.match(s.run("dateTime('2024-10-11T07:06:56')"),/07.*06.*UTC/);
  assert.equal(s.run('gap(3.1155)'),'3 h 07');assert.equal(s.run('gap(0)'),' < 1 min'.trim());
});
test('popup escapes source metadata and shows gear, depth and project',()=>{
  const s=setup();s.context.row={sample_id:'<img onerror=alert(1)>',gear:'2x1m2',min_sample_depth:0,max_sample_depth:100,uvp_project:'Campagne 2024',sample_name:'UVP-1',time_gap_hours:1,match_status:'accepted'};
  const popup=s.run('comparePopup(row)');
  assert.ok(!popup.includes('<img'));assert.ok(popup.includes('&lt;img'));
  for(const text of ['2x1m2','0 à 100','Campagne 2024','UVP-1'])assert.ok(popup.includes(text));
});
test('comparison draws only accepted pairs',async()=>{
  const s=setup();s.element('matches').checked=true;s.element('hours').value='10';
  s.context.fetch=async url=>({ok:true,json:async()=>url.includes('/coverage')?coverage:url.includes('/map')?{uvp:[],filet:[]}:{matches:['accepted','ambiguous'].map(match_status=>({match_status,filet_latitude:60,filet_longitude:-70,uvp_latitude:60.1,uvp_longitude:-70.1}))}});
  await s.run('load()');assert.equal(s.drawn.length,2);
});
test('failed fetch clears stale summary values',async()=>{
  const s=setup();s.element('profiles').textContent='999';s.context.fetch=async()=>({ok:false,status:500});
  await s.run('load()');assert.equal(s.element('profiles').textContent,'—');assert.match(s.element('period').textContent,/Réessayez/);
});
test('late response cannot overwrite a more recent selection',async()=>{
  const s=setup();let release;let calls=0;
  const delayed=new Promise(resolve=>release=resolve);
  s.context.fetch=async url=>{calls++;const first=calls<=2;if(first)await delayed;return {ok:true,json:async()=>url.includes('/map')?{uvp:[],filet:[]}:{...coverage,filters:{zones:[first?'Old':'New']}}}};
  const first=s.run('load()');await s.run('load()');release();await first;
  assert.equal(s.element('title').textContent,'New');
});
test('zone contours follow the layers that still have visible points',()=>{
  const s=setup();
  s.context.zones={type:'FeatureCollection',features:[
    {type:'Feature',properties:{canonical:"Baie d'Hudson"},geometry:{type:'Polygon',coordinates:[[[-90,50],[-70,50],[-70,65],[-90,65],[-90,50]]]}},
    {type:'Feature',properties:{canonical:'Baie de Baffin'},geometry:{type:'Polygon',coordinates:[[[-70,65],[-50,65],[-50,85],[-70,85],[-70,65]]]}}
  ]};
  s.context.points={uvp:[{latitude:75,longitude:-60}],filet:[{latitude:58,longitude:-82}]};
  s.element('matches').checked=false;s.element('uvp').checked=true;s.element('filet').checked=true;
  assert.equal(s.run('visibleZoneFeatures(zones,points).features.length'),2);
  s.element('filet').checked=false;
  assert.deepEqual([...s.run('visibleZoneFeatures(zones,points).features.map(feature=>feature.properties.canonical)')],['Baie de Baffin']);
  s.context.points.uvp=[];
  assert.equal(s.run('visibleZoneFeatures(zones,points).features.length'),0);
});
test('loading state is visible and announced while filters update',()=>{
  const s=setup();s.run('setLoading(true)');
  assert.equal(s.element('mapLoading').hidden,false);
  assert.equal(s.element('mapRegion').attributes['aria-busy'],'true');
  s.run('setLoading(false)');
  assert.equal(s.element('mapLoading').hidden,true);
  assert.equal(s.element('mapRegion').attributes['aria-busy'],undefined);
});
test('removing a year chip clears both ends of the year range',()=>{
  const s=setup();s.element('yearFrom').value='2023';s.element('yearTo').value='2024';s.run("removeFilter('yearRange','')");
  assert.equal(s.element('yearFrom').value,'');assert.equal(s.element('yearTo').value,'');
});
test('legend follows visible layers and comparison mode',()=>{
  const s=setup();s.context.fixture=coverage;s.run('coverageData=fixture');
  s.element('uvp').checked=true;s.element('filet').checked=false;s.element('matches').checked=false;s.run('renderLegend()');
  assert.equal(s.element('legendUvp').hidden,false);assert.equal(s.element('legendCtd').hidden,false);assert.equal(s.element('legendFilet').hidden,true);assert.equal(s.element('legendMatch').hidden,true);assert.equal(s.element('legendEmpty').hidden,true);
  s.element('uvp').checked=false;s.element('matches').checked=false;s.run('renderLegend()');assert.equal(s.element('legendEmpty').hidden,false);
  s.element('matches').checked=true;s.run('renderLegend()');assert.equal(s.element('legendMatch').hidden,false);assert.equal(s.element('legendEmpty').hidden,true);
});
test('empty state names the visible layers and compact summary mirrors the selection',()=>{
  const s=setup();s.context.fixture={...coverage,uvp:{...coverage.uvp,profiles:0},filet:{...coverage.filet,samples:0}};s.run('coverageData=fixture');
  s.element('uvp').checked=true;s.element('filet').checked=false;s.run('renderSummary()');
  assert.match(s.element('emptyDetail').textContent,/Aucune donnée UVP/);assert.equal(s.element('emptyDetail').hidden,false);assert.match(s.element('compactMetrics').textContent,/UVP 0/);
  s.element('uvp').checked=false;s.element('filet').checked=false;s.run('renderSummary()');assert.match(s.element('emptyDetail').textContent,/Aucune couche visible/);assert.equal(s.element('legendEmpty').hidden,false);
});
