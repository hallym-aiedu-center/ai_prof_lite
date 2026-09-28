# core/openai/realtime.py



async def configure_realtime(connection):
    await connection.session.update(
        session={
            "type": "realtime",
            "output_modalities": ["text"],
        }
    )


async def send_text(connection, text: str):
    await connection.conversation.item.create(
        item={
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": text,
                }
            ],
        }
    )

    await connection.response.create()


async def receive_response(connection):
    async for event in connection:
        if event.type == "response.output_text.delta":
            yield {
                "type": "delta",
                "text": event.delta,
            }

        elif event.type == "response.output_text.done":
            yield {
                "type": "text_done",
            }

        elif event.type == "response.done":
            yield {
                "type": "done",
            }
            break

        elif event.type == "error":
            raise RuntimeError(event.error.message)