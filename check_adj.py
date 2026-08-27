with open('jerome_pipeline/pipeline.py') as f:
    content = f.read()
idx = content.find('stage="adjudicator_initial"')
if idx >= 0:
    print(content[idx:idx+1000])
