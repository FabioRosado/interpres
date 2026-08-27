with open('jerome_pipeline/cli.py') as f:
    content = f.read()
idx = content.find('args.command in {"run", "resume"}')
if idx >= 0:
    print(content[idx:idx+1000])
