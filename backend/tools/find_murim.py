import chromadb
client = chromadb.PersistentClient('C:/Users/hibou/Omega_CivicFlow_v4_DB/chroma')
col = client.get_collection('omega_documents_v2')
res = col.get(limit=100000, include=['metadatas'])
companies = set()
for m in res['metadatas']:
    if m and 'company_name' in m:
        name = m['company_name']
        if '무림' in name:
            companies.add(name)
print("Found:", companies)
