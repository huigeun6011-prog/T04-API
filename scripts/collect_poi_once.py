import csv, json, os, re, time, zipfile
from pathlib import Path
from urllib.parse import quote
import requests
from openpyxl import load_workbook
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data'/'raw'/'poi'
BASE.mkdir(parents=True,exist_ok=True)

def env(key):
    for line in (ROOT/'.env').read_text(encoding='utf-8-sig').splitlines():
        if '=' in line and line.split('=',1)[0].strip()==key:
            value=line.split('=',1)[1].strip()
            if len(value)>=2 and value[0] in ('"', "'") and value[-1]==value[0]:
                return value[1:-1].strip()
            return value.strip('"\'').strip()
    return os.getenv(key)

def dirs(kind):
    d=BASE/kind
    (d/'raw').mkdir(parents=True,exist_ok=True); (d/'processed').mkdir(parents=True,exist_ok=True)
    return d

def datafile(pk,detail,hist,kind):
    s=requests.Session(); s.headers['User-Agent']='Mozilla/5.0'; s.get(f'https://www.data.go.kr/data/{pk}/fileData.do',timeout=30)
    r=s.post('https://www.data.go.kr/tcs/dss/selectFileDataDownload.do',data={'publicDataDetailPk':detail,'publicDataPk':pk,'atchFileId':'','fileDetailSn':'1','publicDataTyCode':'PR0051'},timeout=30)
    j=r.json()
    if not j.get('status'): raise RuntimeError('data.go.kr attachment metadata unavailable')
    name=j['dataSetFileDetailInfo'].get('orginlFileNm') or kind+'.csv'
    dl=s.get('https://www.data.go.kr/cmm/cmm/fileDownload.do',params={'atchFileId':j['atchFileId'],'fileDetailSn':j['fileDetailSn'],'dataNm':j['dataSetFileDetailInfo'].get('dataNm','')},timeout=60)
    dl.raise_for_status()
    if len(dl.content)<100 or dl.content.lstrip().startswith(b'<'): raise RuntimeError('data.go.kr download did not return file bytes')
    p=dirs(kind)/'raw'/Path(name).name; p.write_bytes(dl.content); return p

def readcsv(p):
    for enc in ('utf-8-sig','cp949','euc-kr'):
        try:
            with open(p,encoding=enc,newline='') as f: return list(csv.DictReader(f))
        except UnicodeDecodeError: pass
    raise RuntimeError('unknown CSV encoding: '+p.name)

def writecsv(p,rows,fields):
    p.parent.mkdir(parents=True,exist_ok=True)
    with open(p,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)

def val(row,*keys):
    norm={re.sub(r'[^a-z0-9가-힣]','',str(k)).lower():v for k,v in row.items()}
    for k in keys:
        nk=re.sub(r'[^a-z0-9가-힣]','',k).lower()
        for a,v in norm.items():
            if nk==a or nk in a: 
                if v and str(v).strip(): return str(v).strip()
    return ''

api_key=env('DATA_GO_KR_SERVICE_KEY'); vwkey=env('VWORLD_API_KEY')
if not api_key or not vwkey: raise RuntimeError('Required API key is missing (.env)')
fail=[]; counts={}; allrows=[]; geocache={}
def add(kind,rows):
    counts[kind]=len(rows)
    for row in rows: row['facility_type']=kind
    allrows.extend(rows)
def geocode(addr):
    q=addr.strip()
    if not q: return ('','')
    if q in geocache: return geocache[q]
    if not q.startswith('대전'): q='대전광역시 '+q
    for typ in ('ROAD','PARCEL'):
        try:
            r=requests.get('https://api.vworld.kr/req/address',params={'service':'address','request':'getcoord','version':'2.0','crs':'epsg:4326','address':q,'type':typ,'format':'json','key':vwkey},timeout=30)
            j=r.json(); point=j.get('response',{}).get('result',{}).get('point',{})
            x,y=point.get('x',''),point.get('y','')
            if x and y:
                x=float(x); y=float(y)
                if 127.0<=x<=128.0 and 35.8<=y<=36.8:
                    geocache[addr]=(y,x); time.sleep(.35); return (y,x)
        except Exception: pass
    geocache[addr]=('',''); fail.append(f'VWorld 변환 실패: {addr}'); time.sleep(.35); return ('','')

# Library file data
try:
    p=datafile('15086348','uddi:adc2e398-d701-4de1-b103-98ff9e7d8f57','3','library'); raw=readcsv(p); out=[]
    for r in raw:
        name=val(r,'명칭','도서관명','명') or next(iter(r.values()),'')
        addr=val(r,'소재지','주소','소재주소')
        lat,lon=geocode(addr)
        if not name: continue
        out.append({'name':name,'address':addr,'latitude':lat,'longitude':lon,'source':'library'})
    writecsv(dirs('library')/'processed'/'library.csv',out,['name','address','latitude','longitude','source']); add('library',out)
except Exception as e: fail.append('library 수집 실패: '+type(e).__name__)

# Culture API raw response and exhibition filtering
try:
    url='https://apis.data.go.kr/6300000/openapi2022/ctlstt/getctlstt'
    pages=[]; items=[]
    for page in (1,2):
        r=requests.get(url,params={'serviceKey':api_key,'pageNo':page,'numOfRows':100,'type':'json'},timeout=60); r.raise_for_status()
        j=r.json(); pages.append(j)
        (dirs('culture')/'raw'/f'culture_page{page}.json').write_text(json.dumps(j,ensure_ascii=False,indent=2),encoding='utf-8')
        body=j.get('response',{}).get('body',{}); page_items=body.get('items',[]); items.extend(page_items if isinstance(page_items,list) else [page_items])
    out=[]
    for x in items:
        if x.get('fcltyKnd')!='전시관': continue
        addr=x.get('locplc',''); lat,lon=geocode(addr)
        out.append({'name':x.get('fcltyNm',''),'type':x.get('fcltyKnd',''),'address':addr,'latitude':lat,'longitude':lon,'source':'culture'})
    writecsv(dirs('culture')/'processed'/'culture.csv',out,['name','type','address','latitude','longitude','source']); add('culture',out)
except Exception as e: fail.append('culture 수집 실패: '+type(e).__name__)

# Newest Daejeon certified bookstore attachment (2026-11)
try:
    url='https://www.daejeon.go.kr/FileUpload/CommonBoard/normal_0096/20261110101410945.xlsx'
    r=requests.get(url,timeout=60); r.raise_for_status(); p=dirs('bookstore')/'raw'/'2026년 대전광역시 지역서점 인증 목록26.11월 기준.xlsx'; p.write_bytes(r.content)
    ws=load_workbook(p,data_only=True,read_only=True).active
    rows=list(ws.values); header_index=next(i for i,row in enumerate(rows) if any('주소' in str(x or '') for x in row)); headers=[str(x or '').strip() for x in rows[header_index]]; data=[dict(zip(headers,x)) for x in rows[header_index+1:]]
    address_cols=[h for h in headers if any(s in h for s in ('주소','소재지','도로명'))]
    if not address_cols: raise RuntimeError('주소 열 없음; 원본은 보관함')
    out=[]
    for r in data:
        name=val(r,'서점명','서명상호명','상호','업체명','명칭'); addr=val(r,*address_cols)
        if not name: continue
        lat,lon=geocode(addr); out.append({'name':name,'address':addr,'latitude':lat,'longitude':lon,'source':'bookstore'})
    writecsv(dirs('bookstore')/'processed'/'bookstore.csv',out,['name','address','latitude','longitude','source']); add('bookstore',out)
except Exception as e: fail.append('bookstore 수집 실패: '+type(e).__name__)

# Daejeon park API, preserve XML response as served
try:
    u='https://apis.data.go.kr/6300000/parkInfoDaejeonService/parkInfoDaejeonList'
    r=requests.get(u,params={'serviceKey':api_key,'pageNo':1,'numOfRows':500,'type':'json'},timeout=60); r.raise_for_status()
    p=dirs('park')/'raw'/'park.xml'; p.write_bytes(r.content)
    root=ET.fromstring(r.content); out=[]
    for node in root.findall('.//items'):
        d={c.tag:(c.text or '').strip() for c in list(node)}
        name=d.get('title',''); addr=d.get('address',''); lat=d.get('latitude',''); lon=d.get('longitude','')
        if name: out.append({'name':name,'address':addr,'latitude':lat,'longitude':lon,'source':'park'})
    writecsv(dirs('park')/'processed'/'park.csv',out,['name','address','latitude','longitude','source']); add('park',out)
except Exception as e: fail.append('park 수집 실패: '+type(e).__name__)

# Official walk-route file; dataset found is Daecheongho lakeside trail, not a Dulle-gil title
try:
    p=datafile('3075825','uddi:2db4de9c-0110-4458-be9c-82b9c2c55e2c','1','trail'); raw=readcsv(p); out=[]
    for r in raw:
        out.append({'name':val(r,'명칭','코스명','산책길명','이름'),'section':val(r,'구간','구간명'),'course':val(r,'코스','코스내용','경로'),'distance':val(r,'거리'),'time':val(r,'소요시간','시간'),'address':'','latitude':'','longitude':'','source':'trail'})
    writecsv(dirs('trail')/'processed'/'trail.csv',out,['name','section','course','distance','time','address','latitude','longitude','source']); add('trail',out)
except Exception as e: fail.append('trail 수집 실패: '+type(e).__name__)

# Integrated standard facility rows, dedupe identical name/address
merged={}
for r in allrows:
    key=(r.get('name','').strip().casefold(),r.get('address','').strip().casefold())
    if key in merged:
        prev=merged[key]; prev['source']=','.join(sorted(set(prev['source'].split(',')+r['source'].split(','))))
    else: merged[key]=dict(r)
writecsv(BASE/'poi_all.csv',list(merged.values()),['facility_type','name','address','latitude','longitude','source'])
for kind in counts:
    f=dirs(kind)/'processed'/f'{kind}.csv'
    if f.exists():
        rows=readcsv(f)
        for row in rows: row['facility_type']=kind
        writecsv(f,rows,list(dict.fromkeys(['facility_type']+list(rows[0].keys()))) if rows else ['facility_type','name','address','latitude','longitude','source'])
(BASE/'failures.md').write_text('# 수집/변환 실패 기록\n\n'+('\n'.join('- '+x for x in fail) if fail else '- 없음')+'\n',encoding='utf-8')
print(json.dumps({'counts':counts,'merged':len(merged),'failures':fail,'geocode_cache_size':len(geocache)},ensure_ascii=False))
