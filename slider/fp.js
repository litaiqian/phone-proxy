"use strict";

const CRC32_TABLE = [
  0, 1996959894, 3993919788, 2567524794, 124634137, 1886057615, 3915621685, 2657392035, 249268274, 2044508324, 3772115230,
  2547177864, 162941995, 2125561021, 3887607047, 2428444049, 498536548, 1789927666, 4089016648, 2227061214, 450548861,
  1843258603, 4107580753, 2211677639, 325883990, 1684777152, 4251122042, 2321926636, 335633487, 1661365465, 4195302755,
  2366115317, 997073096, 1281953886, 3579855332, 2724688242, 1006888145, 1258607687, 3524101629, 2768942443, 901097722,
  1119000684, 3686517206, 2898065728, 853044451, 1172266101, 3705015759, 2882616665, 651767980, 1373503546, 3369554304,
  3218104598, 565507253, 1454621731, 3485111705, 3099436303, 671266974, 1594198024, 3322730930, 2970347812, 795835527,
  1483230225, 3244367275, 3060149565, 1994146192, 31158534, 2563907772, 4023717930, 1907459465, 112637215, 2680153253,
  3904427059, 2013776290, 251722036, 2517215374, 3775830040, 2137656763, 141376813, 2439277719, 3865271297, 1802195444,
  476864866, 2238001368, 4066508878, 1812370925, 453092731, 2181625025, 4111451223, 1706088902, 314042704, 2344532202,
  4240017532, 1658658271, 366619977, 2362670323, 4224994405, 1303535960, 984961486, 2747007092, 3569037538, 1256170817,
  1037604311, 2765210733, 3554079995, 1131014506, 879679996, 2909243462, 3663771856, 1141124467, 855842277, 2852801631,
  3708648649, 1342533948, 654459306, 3188396048, 3373015174, 1466479909, 544179635, 3110523913, 3462522015, 1591671054,
  702138776, 2966460450, 3352799412, 1504918807, 783551873, 3082640443, 3233442989, 3988292384, 2596254646, 62317068,
  1957810842, 3939845945, 2647816111, 81470997, 1943803523, 3814918930, 2489596804, 225274430, 2053790376, 3826175755,
  2466906013, 167816743, 2097651377, 4027552580, 2265490386, 503444072, 1762050814, 4150417245, 2154129355, 426522225,
  1852507879, 4275313526, 2312317920, 282753626, 1742555852, 4189708143, 2394877945, 397917763, 1622183637, 3604390888,
  2714866558, 953729732, 1340076626, 3518719985, 2797360999, 1068828381, 1219638859, 3624741850, 2936675148, 906185462,
  1090812512, 3747672003, 2825379669, 829329135, 1181335161, 3412177804, 3160834842, 628085408, 1382605366, 3423369109,
  3138078467, 570562233, 1426400815, 3317316542, 2998733608, 733239954, 1555261956, 3268935591, 3050360625, 752459403,
  1541320221, 2607071920, 3965973030, 1969922972, 40735498, 2617837225, 3943577151, 1913087877, 83908371, 2512341634,
  3803740692, 2075208622, 213261112, 2463272603, 3855990285, 2094854071, 198958881, 2262029012, 4057260610, 1759359992,
  534414190, 2176718541, 4139329115, 1873836001, 414664567, 2282248934, 4279200368, 1711684554, 285281116, 2405801727,
  4167216745, 1634467795, 376229701, 2685067896, 3608007406, 1308918612, 956543938, 2808555105, 3495958263, 1231636301,
  1047427035, 2932959818, 3654703836, 1088359270, 936918000, 2847714899, 3736837829, 1202900863, 817233897, 3183342108,
  3401237130, 1404277552, 615818150, 3134207493, 3453421203, 1423857449, 601450431, 3009837614, 3294710456, 1567103746,
  711928724, 3020668471, 3272380065, 1510334235, 755167117
];

const SBOX_TABLE = [
  -9, -84, -50, 59, 115, 102, 57, 125, 94, -15, 15, 2, -72, -98, -79, 38, -56, -49, 76, -26, -117, 60, 90, 9, -107,
  -12, -71, -100, 63, 42, -18, 28, -120, -11, 33, 45, 79, 92, 37, 97, 4, 58, 98, 84, -97, -88, 95, -104, -13, -89, 78,
  -90, 119, -66, 13, -5, 29, -116, -4, -81, 27, 40, -59, -43, 85, 48, -74, 109, -64, 26, 67, -33, -115, 0, -37, -102,
  88, -48, 127, -86, 41, 105, -2, 122, -42, 112, -94, 81, -31, -65, -101, -14, 65, 49, -67, -114, -103, -87, -19, 104,
  66, -73, -34, -78, -45, -27, -109, -108, 47, 61, 86, 43, -54, 25, 64, -35, -44, 53, -112, 36, 73, 89, -82, 51, -32,
  39, -83, 80, -85, -111, 12, -58, 103, -76, -46, -127, 34, 1, -99, 14, -57, 110, 106, 93, -52, 11, 113, 20, -106, 75,
  62, -69, -39, -55, -119, 126, 114, 123, 10, 77, -121, -8, 74, 21, -93, 17, -61, -21, -105, -126, 18, 124, -17, 52,
  -10, -77, -24, -22, 120, -95, -25, 96, -110, 22, -23, 69, -125, -128, -47, -38, -1, 3, -20, 100, 68, 101, 5, 117,
  -122, 44, -51, -36, -41, 24, -80, 30, 82, -63, -40, -92, 91, -6, -53, -124, -62, -28, 111, 19, 50, 108, 70, -68, -29,
  -75, 99, -91, -60, -70, 71, -118, -3, 83, 87, -7, 32, 55, 31, -123, 121, 107, -113, 46, -30, 118, 54, 23, 116, -16,
  7, 6, 35, 16, -96, 56, 72, 8
];

const BLOCK_SIZE = 64;
const KEY_SIZE = 64;
const LENGTH_FIELD_SIZE = 4;
const RANDOM_PREFIX_SIZE = 4;
const RANDOM_ALPHABET = "aZbY0cXdW1eVf2Ug3Th4SiR5jQk6PlO7mNn8MoL9pKqJrIsHtGuFvEwDxCyBzA";
const CUSTOM_BASE64_ALPHABET = "240aYHiQxL\\ZufVlg8sPMR6dGkXvO/Cbw9WDj1ETyIScmeoJz37qthBrU+KNA5pn";
const CUSTOM_BASE64_PAD = "F";
const SERIALIZE_KEYS = ["v", "fp", "u", "h", "ec", "em", "icp"];
const DEFAULT_FP_ARRAY = ["38974258425244", "7396015113652"];
const DEFAULT_SECRET = "14731255234d414cF91356d684E4E8F5F56c8f1bc";

function buildPdDe3Value(userOptions) {
  const globalScope = getGlobalScope();
  const options = userOptions && typeof userOptions === "object" ? userOptions : {};
  const fixedTime =
    typeof options.fixedTime === "number"
      ? options.fixedTime
      : typeof globalScope.__YIDUN_FIXED_TIME === "number"
        ? globalScope.__YIDUN_FIXED_TIME
        : null;
  const seed =
    typeof options.seed === "number"
      ? options.seed
      : typeof globalScope.__YIDUN_SEED === "number"
        ? globalScope.__YIDUN_SEED
        : null;
  const traceEnabled = Boolean(
    options.trace !== undefined ? options.trace : globalScope.__YIDUN_TRACE_ENABLED
  );
  const trace = traceEnabled ? { blocks: [] } : null;
  const randomSequence =
    Array.isArray(options.randomSequence)
      ? options.randomSequence.slice()
      : Array.isArray(globalScope.__YIDUN_RANDOM_SEQ)
        ? globalScope.__YIDUN_RANDOM_SEQ
        : null;
  const state = {
    globalScope,
    fixedTime,
    seed: typeof seed === "number" ? seed >>> 0 : null,
    randomSequence
  };

  const payload = { v: options.version || "v1.1" };
  if (options.icp) {
    payload.icp = options.icp;
  }
  payload.h = options.host || "m.kepuchina.cn";

  const timestampCore = getCurrentTime(state) + 900000;
  payload.u = buildRandomString(3, state) + timestampCore + buildRandomString(3, state);

  setTrace(trace, "runtime", {
    fixedTime: typeof fixedTime === "number" ? fixedTime : "__random__",
    seed: typeof seed === "number" ? seed : "__random__",
    traceEnabled
  });
  setTrace(trace, "u", payload.u);
  setTrace(trace, "timestampCore", timestampCore);

  const fpArray = normalizeFingerprintArray(options.fpArray);
  try {
    setTrace(trace, "fpArray", fpArray);
    if (fpArray.length > 0) {
      payload.fp = fpArray.join(",");
    } else {
      payload.fp = "0000000000";
      payload.ec = "1";
    }
  } catch (_error) {
    payload.fp = "0000000000";
    payload.ec = "1";
  }
  setTrace(trace, "payloadWithFp", payload);

  let result;
  try {

    const serializedPayload = serializePayload(payload);
    const secret = options.secret || DEFAULT_SECRET;
    if (secret == null) {
      throw Error("1008");
    }

    setTrace(trace, "serializedPayload", serializedPayload);
    setTrace(trace, "secretLiteral", secret);
    setTrace(trace, "messagePlain", serializedPayload);

    const payloadCrcHex = crcHexFromBytes(serializedPayload == null ? [] : stringToEncodedBytes(serializedPayload));
    const messageBytes = stringToEncodedBytes(serializedPayload + payloadCrcHex);
    const secretBytes = stringToEncodedBytes(secret);

    setTrace(trace, "payloadCrcHex", payloadCrcHex);
    setTrace(trace, "messageBytesRaw", messageBytes);
    setTrace(trace, "secretBytesRaw", secretBytes);

    const randomBytes = [];
    for (let index = 0; index < RANDOM_PREFIX_SIZE; index++) {
      randomBytes[index] = toSignedByte(Math.floor(nextRandom(state) * 256));
    }
    setTrace(trace, "randomBytes", randomBytes);

    const expandedSecret = expandKey(secretBytes);
    const mixedSecret = xorByteArrays(expandedSecret, expandKey(randomBytes));
    const secretSeed = expandKey(mixedSecret);

    setTrace(trace, "secretExpanded", expandedSecret);
    setTrace(trace, "secretMixed", mixedSecret);
    setTrace(trace, "secretExpandedFinal", secretSeed);
    setTrace(trace, "prevSeed", secretSeed);

    const paddedMessage = padMessage(messageBytes);
    const messageBlocks = splitIntoBlocks(paddedMessage, BLOCK_SIZE);
    const cipherBytes = [];
    let previousBlock = secretSeed;

    copyBytes(randomBytes, 0, cipherBytes, 0, RANDOM_PREFIX_SIZE);
    setTrace(trace, "paddedMessageBytes", paddedMessage);
    setTrace(trace, "messageBlocks", messageBlocks);
    setTrace(trace, "outputPrefixBytes", cipherBytes.slice());

    for (let blockIndex = 0; blockIndex < messageBlocks.length; blockIndex++) {
      const sourceBlock = messageBlocks[blockIndex];
      setBlockTrace(trace, blockIndex, "sourceBlock", sourceBlock);

      const xor37 = sourceBlock.map((value) => xorSignedByte(value, toSignedByte(37)));
      setBlockTrace(trace, blockIndex, "xor37", xor37);

      const xor35Desc = [];
      let descMask = toSignedByte(35);
      for (let index = 0; index < xor37.length; index++) {
        xor35Desc.push(xorSignedByte(xor37[index], descMask--));
      }
      setBlockTrace(trace, blockIndex, "xor35Desc", xor35Desc);

      const addNeg44 = [];
      let addMask = toSignedByte(-44);
      for (let index = 0; index < xor35Desc.length; index++) {
        addNeg44.push(addSignedByte(xor35Desc[index], addMask++));
      }
      setBlockTrace(trace, blockIndex, "addNeg44", addNeg44);

      const xorKey = xorByteArrays(addNeg44, secretSeed);
      setBlockTrace(trace, blockIndex, "xorKey", xorKey);

      const addPrev = addWithPreviousBlock(xorKey, previousBlock);
      setBlockTrace(trace, blockIndex, "addPrev", addPrev);

      const xorPrev = xorByteArrays(addPrev, previousBlock);
      setBlockTrace(trace, blockIndex, "xorPrev", xorPrev);

      const sbox1 = applySbox(xorPrev);
      setBlockTrace(trace, blockIndex, "sbox1", sbox1);

      const sbox2 = applySbox(sbox1);
      setBlockTrace(trace, blockIndex, "sbox2", sbox2);
      setBlockTrace(trace, blockIndex, "outBlock", sbox2);

      copyBytes(sbox2, 0, cipherBytes, blockIndex * BLOCK_SIZE + RANDOM_PREFIX_SIZE, BLOCK_SIZE);
      previousBlock = sbox2;
    }

    const base64Chunks = encodeCustomBase64Chunks(cipherBytes);
    const ciphertext = base64Chunks.join("");

    setTrace(trace, "cipherBytes", cipherBytes);
    setTrace(trace, "base64Chunks", base64Chunks);
    setTrace(trace, "ciphertext", ciphertext);

    result = ciphertext;
  } catch (error) {
    setTrace(trace, "error", {
      message: error.message,
      stack: error.stack
    });
    result = serializePayload({
      ec: "2",
      em: error.message
    });
  }

  const resultWithTimestamp = result + ":" + timestampCore;
  setTrace(trace, "resultWithTimestamp", resultWithTimestamp);

  if (traceEnabled) {
    globalScope.__YIDUN_TRACE = trace;
  }
  globalScope.__YIDUN_LAST_RESULT = resultWithTimestamp;
  return resultWithTimestamp;
}

function getGlobalScope() {
  if (typeof globalThis !== "undefined") {
    return globalThis;
  }
  return Function("return this")();
}

function normalizeFingerprintArray(fpArray) {
  if (Array.isArray(fpArray)) {
    return fpArray.slice();
  }
  return DEFAULT_FP_ARRAY.slice();
}

function getCurrentTime(state) {
  if (typeof state.fixedTime === "number") {
    return state.fixedTime;
  }
  return new state.globalScope.Date().getTime();
}

function nextRandom(state) {
  if (Array.isArray(state.randomSequence) && state.randomSequence.length > 0) {
    return state.randomSequence.shift();
  }
  if (state.seed != null) {
    state.seed = (1664525 * state.seed + 1013904223) >>> 0;
    return state.seed / 4294967296;
  }
  return Math.random();
}

function buildRandomString(length, state) {
  const chars = [];
  for (let index = 0; index < length; index++) {
    chars.push(RANDOM_ALPHABET.charAt(Math.floor(nextRandom(state) * RANDOM_ALPHABET.length)));
  }
  return chars.join("");
}

function serializePayload(payload) {
  if (payload == null || typeof payload !== "object") {
    return payload;
  }
  let result = "{";
  let hasProperty = false;
  for (const key of SERIALIZE_KEYS) {
    if (Object.prototype.hasOwnProperty.call(payload, key)) {
      hasProperty = true;
      let value = String(payload[key]);
      value = value.replace(/'/g, "\\'").replace(/"/g, '\\"');
      result += `'${key}':'${value}',`;
    }
  }
  if (hasProperty) {
    result = result.slice(0, -1);
  }
  return result + "}";
}

function allocateZeroBytes(length) {
  const result = [];
  for (let index = 0; index < length; index++) {
    result[index] = 0;
  }
  return result;
}

function applySbox(bytes) {
  if (bytes == null) {
    return null;
  }
  const result = [];
  for (let index = 0; index < bytes.length; index++) {
    const value = bytes[index];
    result[index] = SBOX_TABLE[((value >>> 4) & 15) * 16 + (value & 15)];
  }
  return result;
}

function expandKey(bytes) {
  if (bytes == null || bytes.length === 0) {
    return allocateZeroBytes(KEY_SIZE);
  }
  if (bytes.length >= KEY_SIZE) {
    return bytes.slice(0, KEY_SIZE);
  }
  const result = [];
  for (let index = 0; index < KEY_SIZE; index++) {
    result[index] = bytes[index % bytes.length];
  }
  return result;
}

function crcHexFromBytes(bytes) {
  let crc = -1;
  if (bytes != null) {
    for (let index = 0; index < bytes.length; index++) {
      const tableIndex = (crc ^ bytes[index]) & 255;
      crc = (crc >>> 8) ^ CRC32_TABLE[tableIndex];
    }
  }
  const hash = crc ^ -1;
  return [(hash >>> 24) & 255, (hash >>> 16) & 255, (hash >>> 8) & 255, hash & 255]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

function stringToEncodedBytes(input) {
  if (input == null) {
    return input;
  }
  const encoded = encodeURIComponent(input);
  const result = [];
  for (let index = 0; index < encoded.length; index++) {
    if (encoded.charAt(index) === "%") {
      if (!(index + 2 < encoded.length)) {
        throw Error(1009);
      }
      result.push(hexToSignedBytes(encoded.charAt(++index) + encoded.charAt(++index))[0]);
    } else {
      result.push(encoded.charCodeAt(index));
    }
  }
  return result;
}

function hexToSignedBytes(hexString) {
  if (hexString == null || hexString.length === 0) {
    return [];
  }
  const normalized = String(hexString);
  const result = [];
  for (let index = 0; index < normalized.length / 2; index++) {
    const high = parseInt(normalized.charAt(index * 2), 16) << 4;
    const low = parseInt(normalized.charAt(index * 2 + 1), 16);
    result[index] = toSignedByte(high + low);
  }
  return result;
}

function toSignedByte(value) {
  if (value < -128) {
    return toSignedByte(128 - (-128 - value));
  }
  if (value >= -128 && value <= 127) {
    return value;
  }
  if (value > 127) {
    return toSignedByte(-129 + value - 127);
  }
  throw Error(1001);
}

function encodeBase64Chunk(bytes, offset, byteCount) {
  const output = [];
  if (byteCount === 1) {
    const byte0 = bytes[offset];
    const byte1 = 0;
    output.push(CUSTOM_BASE64_ALPHABET[(byte0 >>> 2) & 63]);
    output.push(CUSTOM_BASE64_ALPHABET[((byte0 << 4) & 48) + ((byte1 >>> 4) & 15)]);
    output.push(CUSTOM_BASE64_PAD);
    output.push(CUSTOM_BASE64_PAD);
  } else if (byteCount === 2) {
    const byte0 = bytes[offset];
    const byte1 = bytes[offset + 1];
    const byte2 = 0;
    output.push(CUSTOM_BASE64_ALPHABET[(byte0 >>> 2) & 63]);
    output.push(CUSTOM_BASE64_ALPHABET[((byte0 << 4) & 48) + ((byte1 >>> 4) & 15)]);
    output.push(CUSTOM_BASE64_ALPHABET[((byte1 << 2) & 60) + ((byte2 >>> 6) & 3)]);
    output.push(CUSTOM_BASE64_PAD);
  } else {
    if (byteCount !== 3) {
      throw Error("1111");
    }
    const byte0 = bytes[offset];
    const byte1 = bytes[offset + 1];
    const byte2 = bytes[offset + 2];
    output.push(CUSTOM_BASE64_ALPHABET[(byte0 >>> 2) & 63]);
    output.push(CUSTOM_BASE64_ALPHABET[((byte0 << 4) & 48) + ((byte1 >>> 4) & 15)]);
    output.push(CUSTOM_BASE64_ALPHABET[((byte1 << 2) & 60) + ((byte2 >>> 6) & 3)]);
    output.push(CUSTOM_BASE64_ALPHABET[byte2 & 63]);
  }
  return output.join("");
}

function copyBytes(source, sourceStart, target, targetStart, length) {
  if (source == null || source.length === 0) {
    return target;
  }
  if (target == null) {
    throw Error("canvas exception");
  }
  if (source.length < length) {
    throw Error("hashCode");
  }
  for (let index = 0; index < length; index++) {
    target[targetStart + index] = source[sourceStart + index];
  }
  return target;
}

function intToBytes(intValue) {
  return [
    (intValue >>> 24) & 255,
    (intValue >>> 16) & 255,
    (intValue >>> 8) & 255,
    intValue & 255
  ];
}

function xorByteArrays(left, right) {
  if (left == null || right == null || left.length !== right.length) {
    return left;
  }
  const result = [];
  for (let index = 0; index < left.length; index++) {
    result[index] = xorSignedByte(left[index], right[index]);
  }
  return result;
}

function xorSignedByte(left, right) {
  return toSignedByte(toSignedByte(left) ^ toSignedByte(right));
}

function addSignedByte(left, right) {
  return toSignedByte(left + right);
}

function addWithPreviousBlock(bytes, previousBlock) {
  if (bytes == null) {
    return null;
  }
  if (previousBlock == null) {
    return bytes.slice();
  }
  const result = [];
  for (let index = 0; index < bytes.length; index++) {
    result[index] = toSignedByte(bytes[index] + previousBlock[index % previousBlock.length]);
  }
  return result;
}

// 把消息补齐到 64 字节分组，并在末尾追加 4 字节长度字段。
function padMessage(messageBytes) {
  if (messageBytes == null || messageBytes.length === 0) {
    return allocateZeroBytes(BLOCK_SIZE);
  }

  const messageLength = messageBytes.length;
  const paddingZeros =
    messageLength % BLOCK_SIZE <= BLOCK_SIZE - LENGTH_FIELD_SIZE
      ? BLOCK_SIZE - (messageLength % BLOCK_SIZE) - LENGTH_FIELD_SIZE
      : BLOCK_SIZE * 2 - (messageLength % BLOCK_SIZE) - LENGTH_FIELD_SIZE;
  const result = [];

  copyBytes(messageBytes, 0, result, 0, messageLength);
  for (let index = 0; index < paddingZeros; index++) {
    result[messageLength + index] = 0;
  }
  copyBytes(intToBytes(messageLength), 0, result, messageLength + paddingZeros, LENGTH_FIELD_SIZE);
  return result;
}

function splitIntoBlocks(bytes, blockSize) {
  if (bytes == null || bytes.length % blockSize !== 0) {
    throw Error("1005");
  }
  const blocks = [];
  let sourceIndex = 0;
  for (let blockIndex = 0; blockIndex < bytes.length / blockSize; blockIndex++) {
    blocks[blockIndex] = [];
    for (let innerIndex = 0; innerIndex < blockSize; innerIndex++) {
      blocks[blockIndex][innerIndex] = bytes[sourceIndex++];
    }
  }
  return blocks;
}

function encodeCustomBase64Chunks(bytes) {
  if (bytes == null) {
    return null;
  }
  if (bytes.length === 0) {
    return [];
  }
  const chunks = [];
  const chunkSize = 3;
  for (let index = 0; index < bytes.length; ) {
    if (index + chunkSize > bytes.length) {
      chunks.push(encodeBase64Chunk(bytes, index, bytes.length - index));
      break;
    }
    chunks.push(encodeBase64Chunk(bytes, index, chunkSize));
    index += chunkSize;
  }
  return chunks;
}

function cloneTraceValue(value) {
  if (value === undefined) {
    return "__undefined__";
  }
  if (value === null) {
    return null;
  }
  if (Array.isArray(value)) {
    return value.map(cloneTraceValue);
  }
  if (typeof value === "object") {
    const result = {};
    for (const key in value) {
      if (Object.prototype.hasOwnProperty.call(value, key)) {
        result[key] = cloneTraceValue(value[key]);
      }
    }
    return result;
  }
  return value;
}

function setTrace(trace, key, value) {
  if (trace) {
    trace[key] = cloneTraceValue(value);
  }
  return value;
}

function setBlockTrace(trace, blockIndex, key, value) {
  if (trace) {
    let blockTrace = trace.blocks[blockIndex];
    if (!blockTrace) {
      blockTrace = { index: blockIndex };
      trace.blocks[blockIndex] = blockTrace;
    }
    blockTrace[key] = cloneTraceValue(value);
  }
  return value;
}

if (typeof globalThis !== "undefined") {
  globalThis.buildPdDe3Value = buildPdDe3Value;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = buildPdDe3Value;
  if (typeof require !== "undefined" && require.main === module) {
    console.log(buildPdDe3Value());
  }
} else if (typeof globalThis !== "undefined" && globalThis.__YIDUN_AUTO_RUN !== false) {
  globalThis.__YIDUN_LAST_RESULT = buildPdDe3Value();
}
