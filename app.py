from factorylib import create_app
import stream_adapter

app = create_app("stream", "ストリーム データ送信", stream_adapter)
