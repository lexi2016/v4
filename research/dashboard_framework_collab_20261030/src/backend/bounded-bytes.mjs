import {check} from './contracts.mjs';
export async function boundedBytes(stream, max = 16*1024*1024) {
    const reader = stream?.getReader();
    check(reader, 'BODY_REQUIRED');
    const parts = [];
    let length = 0;
    try {
        for (;;) {
            const { done, value } = await reader.read();
            if (done)
                break;
            check(value instanceof Uint8Array, 'INVALID_BODY');
            length += value.byteLength;
            if (length > max) {
                await reader.cancel();
                check(false,'OBJECT_TOO_LARGE',413);
            }
            parts.push(value);
        }
    }
    finally {
        reader.releaseLock();
    }
    const result = new Uint8Array(length);
    let offset = 0;
    for (const p of parts) {
        result.set(p, offset);
        offset += p.length;
    }
    return result;
}
