import { deflateRawSync } from "node:zlib";

type Entry = { name: string; content: string };

function crc32(bytes: Uint8Array) {
  let value = 0xffffffff;
  for (const byte of bytes) {
    value ^= byte;
    for (let bit = 0; bit < 8; bit++) value = (value >>> 1) ^ (value & 1 ? 0xedb88320 : 0);
  }
  return (value ^ 0xffffffff) >>> 0;
}

export function zipEntries(entries: Entry[], fileName = "skill.zip", deflate = false) {
  const encoder = new TextEncoder();
  const local: Uint8Array[] = [];
  const central: Uint8Array[] = [];
  let offset = 0;
  for (const entry of entries) {
    const name = encoder.encode(entry.name);
    const body = encoder.encode(entry.content);
    const packed = deflate ? deflateRawSync(body) : body;
    const crc = crc32(body);
    const localRecord = new Uint8Array(30 + name.length + packed.length);
    const localView = new DataView(localRecord.buffer);
    localView.setUint32(0, 0x04034b50, true);
    localView.setUint16(4, 20, true);
    localView.setUint16(8, deflate ? 8 : 0, true);
    localView.setUint32(14, crc, true);
    localView.setUint32(18, packed.length, true);
    localView.setUint32(22, body.length, true);
    localView.setUint16(26, name.length, true);
    localRecord.set(name, 30);
    localRecord.set(packed, 30 + name.length);
    local.push(localRecord);

    const centralRecord = new Uint8Array(46 + name.length);
    const centralView = new DataView(centralRecord.buffer);
    centralView.setUint32(0, 0x02014b50, true);
    centralView.setUint16(4, 20, true);
    centralView.setUint16(6, 20, true);
    centralView.setUint16(10, deflate ? 8 : 0, true);
    centralView.setUint32(16, crc, true);
    centralView.setUint32(20, packed.length, true);
    centralView.setUint32(24, body.length, true);
    centralView.setUint16(28, name.length, true);
    centralView.setUint32(42, offset, true);
    centralRecord.set(name, 46);
    central.push(centralRecord);
    offset += localRecord.length;
  }
  const centralSize = central.reduce((size, entry) => size + entry.length, 0);
  const end = new Uint8Array(22);
  const view = new DataView(end.buffer);
  view.setUint32(0, 0x06054b50, true);
  view.setUint16(8, entries.length, true);
  view.setUint16(10, entries.length, true);
  view.setUint32(12, centralSize, true);
  view.setUint32(16, offset, true);
  return new File([...local, ...central, end], fileName, { type: "application/zip" });
}

export function skillZip(name: string, description: string, body: string, extras: Entry[] = []) {
  return zipEntries([
    { name: `${name}/SKILL.md`, content: `---\nname: ${name}\ndescription: ${description}\ntags: [teaching]\n---\n\n${body}\n` },
    ...extras,
  ], `${name}.zip`);
}
