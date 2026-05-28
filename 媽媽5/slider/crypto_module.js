window = global;
var objectToString = {}.toString;
var DEVICE_TOKEN_KEY = "ujg3ps2znyw";

document = {
  body: {},
  createElement: function (tag_name) {
    if (tag_name === "div") {
      return div;
    }
  },
  getElementById: function (ele_id) {
  },
};

var utils = {
  slice: function (_0x182149, _0x566683, _0x1c54e4) {
    var _0x111d78 = [];
    var _0x58daa9 = _0x566683 || 0;
    for (var _0x39dab3 = _0x1c54e4 || _0x182149["length"]; _0x58daa9 < _0x39dab3; _0x58daa9++) {
      _0x111d78["push"](_0x58daa9);
    }
    return _0x111d78;
  },
  getObjKey: function (_0x453521, _0x1c2c5f) {
    for (var _0x24f6d4 in _0x453521)
      if (_0x453521["hasOwnProperty"](_0x24f6d4) && _0x453521[_0x24f6d4] === _0x1c2c5f) {
        return _0x24f6d4;
      }
  },
  typeOf: function (_0x289fc3) {
    return null == _0x289fc3 ? String(_0x289fc3) : objectToString["call"](_0x289fc3)["slice"](8, -1)["toLowerCase"]();
  },
  isFn: function (_0x7e7208) {
    return "function" == typeof _0x7e7208;
  },
  log: function (_0x72ec12, _0x3bea3e) {
    var _0x4c8ed6 = ["info", "warn", "error"];
    return "string" == typeof _0x72ec12 && ~_0x4c8ed6["indexOf"](_0x72ec12)
      ? void (console && console[_0x72ec12]("[NECaptcha] " + _0x3bea3e))
      : void utils["error"]('util.log(type, msg): "type" must be one string of ' + _0x4c8ed6["toString"]());
  },
  warn: function (_0x17a96a) {
    utils["log"]("warn", _0x17a96a);
  },
  error: function (_0x4a5640) {
    utils["log"]("error", _0x4a5640);
  },
  assert: function (_0x50f82a, _0x37f198) {
    if (!_0x50f82a) {
      throw new Error("[NECaptcha] " + _0x37f198);
    }
  },
  msie: function _0x3ee98c() {
    var _0x5e7df5 = navigator["userAgent"];
    var _0x594b99 = parseInt((/msie (\d+)/["exec"](_0x5e7df5["toLowerCase"]()) || [])[1]);
    isNaN(_0x594b99) && (_0x594b99 = parseInt((/trident\/.*; rv:(\d+)/["exec"](_0x5e7df5["toLowerCase"]()) || [])[1]));
    return _0x594b99;
  },
  now: function () {
    return new Date()["getTime"]();
  },
  getIn: function (_0x1d1045, _0x4ca40a, _0x174f2f) {
    if ("[object Object]" !== Object["prototype"]["toString"]["call"](_0x1d1045)) {
      return _0x174f2f;
    }
    "string" == typeof _0x4ca40a && (_0x4ca40a = _0x4ca40a["split"]("."));
    var _0x2cab00 = 0;
    for (var _0x58cb9b = _0x4ca40a["length"]; _0x2cab00 < _0x58cb9b; _0x2cab00++) {
      var _0x3597b5 = _0x4ca40a[_0x2cab00];
      if (_0x2cab00 < _0x58cb9b - 1 && !_0x1d1045[_0x3597b5]) {
        return _0x174f2f;
      }
      _0x1d1045 = _0x1d1045[_0x3597b5];
    }
    return _0x1d1045;
  },
  raf: function _0x137034(_0x1b657f) {
    var _0xa22aaf =
      window["requestAnimationFrame"] ||
      window["webkitRequestAnimationFrame"] ||
      function (_0x4ddb6f) {
        window["setTimeout"](_0x4ddb6f, 16);
      };
    _0xa22aaf(_0x1b657f);
  },
  nextFrame: function (_0x12fb5f) {
    utils["raf"](function () {
      return utils["raf"](_0x12fb5f);
    });
  },
  sample: function (_0x4f8a50, _0x2720fb) {
    var _0x1f84b9 = _0x4f8a50["length"];
    if (_0x1f84b9 <= _0x2720fb) {
      return _0x4f8a50;
    }
    var _0x35f7ff = [];
    var _0x446efa = 0;
    for (var _0x171ba7 = 0; _0x171ba7 < _0x1f84b9; _0x171ba7++) {
      _0x171ba7 >= (_0x446efa * (_0x1f84b9 - 1)) / (_0x2720fb - 1) && (_0x35f7ff["push"](_0x4f8a50[_0x171ba7]), (_0x446efa += 1));
    }
    return _0x35f7ff;
  },
  template: function (_0x42b80e, _0x48bd17) {
    var _0x284539 = {
      start: "<%",
      end: "%>",
      interpolate: /<%=(.+?)%>/g,
    };
    function _0x5abe64(_0x1ff148) {
      return _0x1ff148["replace"](/([.*+?^${}()|[\]\/\\])/g, "\\$1");
    }
    var _0x54e0e4 = new RegExp("'(?=[^" + _0x284539["end"]["substr"](0, 1) + "]*" + _0x5abe64(_0x284539["end"]) + ")", "g");
    var _0x55626a = new Function(
      "obj",
      "var p=[],print=function(){p.push.apply(p,arguments);};with(obj){p.push('" +
        _0x42b80e["replace"](/[\r\t\n]/g, " ")
          ["replace"](_0x54e0e4, "\t")
          ["split"]("'")
          ["join"]("\\'")
          ["split"]("\t")
          ["join"]("'")
          ["replace"](_0x284539["interpolate"], "',$1,'")
          ["split"](_0x284539["start"])
          ["join"]("');")
          ["split"](_0x284539["end"])
          ["join"]("p.push('") +
        "');}return p.join('');",
    );
    return _0x48bd17 ? _0x55626a(_0x48bd17) : _0x55626a;
  },
  uuid: function _0x2b4c4d(_0x5aa56e, _0x3bfa37) {
    var _0x171c6a = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"["split"]("");
    var _0xaa2517 = [];
    var _0x3a6676 = void 0;
    if (((_0x3bfa37 = _0x3bfa37 || _0x171c6a["length"]), _0x5aa56e)) {
      for (_0x3a6676 = 0; _0x3a6676 < _0x5aa56e; _0x3a6676++) {
        _0xaa2517[_0x3a6676] = _0x171c6a[0 | (Math["random"]() * _0x3bfa37)];
      }
    } else {
      var _0x4fe738 = void 0;
      _0xaa2517[8] = _0xaa2517[13] = _0xaa2517[18] = _0xaa2517[23] = "-";
      _0xaa2517[14] = "4";
      for (_0x3a6676 = 0; _0x3a6676 < 36; _0x3a6676++) {
        _0xaa2517[_0x3a6676] ||
          ((_0x4fe738 = 0 | (16 * Math["random"]())), (_0xaa2517[_0x3a6676] = _0x171c6a[19 === _0x3a6676 ? (3 & _0x4fe738) | 8 : _0x4fe738]));
      }
    }
    return _0xaa2517["join"]("");
  },
  reverse: function (_0x5c0f77) {
    return Array["isArray"](_0x5c0f77)
      ? _0x5c0f77["reverse"]()
      : "string" === utils["typeOf"](_0x5c0f77)
        ? _0x5c0f77["split"]("")["reverse"]()["join"]("")
        : _0x5c0f77;
  },
  encodeUrlParams: function (_0x21a041) {
    var _0x3693ae = [];
    for (var _0xfe4e89 in _0x21a041)
      _0x21a041["hasOwnProperty"](_0xfe4e89) &&
        _0x3693ae["push"](window["encodeURIComponent"](_0xfe4e89) + "=" + window["encodeURIComponent"](_0x21a041[_0xfe4e89]));
    return _0x3693ae["join"]("&");
  },
  adsorb: function (_0x619d8d, _0x2f9030, _0x43bcc7) {
    return void 0 === _0x2f9030 || null === _0x2f9030 || void 0 === _0x43bcc7 || null === _0x43bcc7
      ? _0x619d8d
      : Math["max"](Math["min"](_0x619d8d, _0x43bcc7), _0x2f9030);
  },
  unique2DArray: function (_0x201038) {
    var _0x56a8ee = arguments["length"] > 1 && void 0 !== arguments[1] ? arguments[1] : 0;
    if (!Array["isArray"](_0x201038)) {
      return _0x201038;
    }
    var _0x61ed54 = {};
    var _0xcd81a8 = [];
    var _0xead976 = 0;
    for (var _0x4fef16 = _0x201038["length"]; _0xead976 < _0x4fef16; _0xead976++) {
      var _0x125813 = _0x201038[_0xead976][_0x56a8ee];
      null === _0x125813 || void 0 === _0x125813 || _0x61ed54[_0x125813] || ((_0x61ed54[_0x125813] = true), _0xcd81a8["push"](_0x201038[_0xead976]));
    }
    return _0xcd81a8;
  },
  setDeviceToken: function (_0x55dcb9) {
    try {
      window["localStorage"]["setItem"](DEVICE_TOKEN_KEY, _0x55dcb9);
    } catch (_0x29b015) {
      return null;
    }
  },
  getDeviceToken: function () {
    try {
      var _0x281e33 = window["localStorage"]["getItem"](DEVICE_TOKEN_KEY);
      return _0x281e33;
    } catch (_0x5acec3) {
      return null;
    }
  },
};

var cryptoConstants = {
  __SBOX__:
    "a7be3f3933fa8c5fcf86c4b6908b569ba1e26c1a6d7cfbf60ae4b00e074a194dac4b73e7f898541159a39d08183b76eedee3ed341e6685d2357440158394b1ff03a9004cbbb5ca7dcb7f41489a16e03dcc9c71eb3c9796685b1d01b4d56193a6e1f1a2470445c191ae49c5d82765dc82c350f263387a24a502fcbf442e2dddaad0e936d9ea22b89275307b42518fbc3a626ba806d4ecd6d725f50cc8c72fefa4551ccd6fc9b2b7ab954f815c7264c6e51f4eaf99885a79892b1b60a0b3526e57ba5d178d370958847eb9fd28f9ce0bc023f4148a2adfe632126769057043d3bd8eda0df7872629f3809ef05310e83113216afe202c460fc23e789f77d1addb5e",
  __ROUND_KEY__: "037606da0296055c",
  __SEED_KEY__: "fd6a43ae25f74398b61c03c83be37449",
  __BASE64_ALPHABET__: "MB.CfHUzEeJpsuGkgNwhqiSaI4Fd9L6jYKZAxn1/Vml0c5rbXRP+8tD3QTO2vWyo",
  __BASE64_PADDING__: "7",
};

const SBOX_HEX = cryptoConstants.__SBOX__;
const SEED_KEY = cryptoConstants.__SEED_KEY__;
const ROUND_KEY_HEX = cryptoConstants.__ROUND_KEY__;
const DEFAULT_BASE64_ALPHABET = cryptoConstants.__BASE64_ALPHABET__;
const DEFAULT_BASE64_PADDING = cryptoConstants.__BASE64_PADDING__;
const SAMPLE_COUNT = 50;
const DEFAULT_CAPTCHA_WIDTH = 320;
const DEFAULT_SLIDER_WIDTH = 40;
const DEFAULT_JIGSAW_WIDTH = 61;
const DEFAULT_START_LEFT = 0;
function generateCbValue() {
  var cbConfig = {
    suffix: "m25b40",
    code: "vfnv46",
    pos: [1, 10, 12, 13, 26, 31],
  };
  var cbOptions = cbConfig || {};
  var injectedCode = cbOptions["code"];
  var injectedPositions = cbOptions["pos"];
  var randomUuid = utils["uuid"](32);
  if (injectedCode && injectedPositions && Array["isArray"](injectedPositions)) {
    var uuidChars = randomUuid["split"]("");
    for (var codeIndex = 0; codeIndex < injectedPositions["length"]; codeIndex++) {
      uuidChars[injectedPositions[codeIndex]] = injectedCode["charAt"](codeIndex);
    }
    randomUuid = uuidChars["join"]("");
  }
  //   console.log(randomUuid    );
  //   kvsfoE77UifbnviMXtdXOnYohV4i0sg6

  return encryptWithAes(randomUuid);
}

function encryptWithAes(plainText) {
  const plainTextBytes = stringToBytes(plainText);
  const seedBlockAndIv = buildSeedBlockAndIv();
  const [seedBlock, ivBytes] = destructureArray(seedBlockAndIv, 2);

  const crcBytes = stringToBytes(genCrc32(plainTextBytes));
  const paddedBytes = padBytesWithLength([].concat(cloneArray(plainTextBytes), cloneArray(crcBytes)));
  const messageBlocks = splitInto64ByteBlocks(paddedBytes);

  const outputBytes = [].concat(cloneArray(ivBytes));
  let previousBlock = seedBlock;

  for (let blockIndex = 0, blockCount = messageBlocks.length; blockIndex < blockCount; blockIndex++) {
    let encryptedBlock = xors(applyRoundOperations(messageBlocks[blockIndex]), seedBlock);
    const shiftedBlock = shiftBytes(encryptedBlock, previousBlock);
    encryptedBlock = xors(shiftedBlock, previousBlock);
    previousBlock = substituteWithSbox(substituteWithSbox(encryptedBlock));
    copyToBytes(previousBlock, 0, outputBytes, blockIndex * 64 + 4, 64);
  }

  return base64EncodeWithCustomAlphabet(outputBytes);
}

function substituteWithSbox(bytes) {
  const sboxBytes = hexStringToBytes(SBOX_HEX);

  function lookupSbox(byteValue) {
    return sboxBytes[((byteValue >>> 4) & 15) * 16 + (byteValue & 15)];
  }

  if (!bytes.length) {
    return [];
  }

  const result = [];
  for (let index = 0, length = bytes.length; index < length; index++) {
    result[index] = lookupSbox(bytes[index]);
  }
  return result;
}
function buildSeedBlockAndIv() {
  let seedBytes = stringToBytes(SEED_KEY);
  const ivBytes = random4Bytes();

  seedBytes = normalizeTo64Bytes(seedBytes);
  seedBytes = xors(seedBytes, normalizeTo64Bytes(ivBytes));
  seedBytes = normalizeTo64Bytes(seedBytes);

  return [seedBytes, ivBytes];
}

const destructureArray = (function () {
  function sliceIterator(iterable, limit) {
    const result = [];
    let normalCompletion = true;
    let didThrow = false;
    let thrownError = undefined;

    try {
      let step;
      const iterator = iterable[Symbol.iterator]();
      while (!(normalCompletion = (step = iterator.next()).done) && (result.push(step.value), !limit || result.length !== limit)) {}
    } catch (error) {
      didThrow = true;
      thrownError = error;
    } finally {
      try {
        if (!normalCompletion && iterator.return) {
          iterator.return();
        }
      } finally {
        if (didThrow) {
          throw thrownError;
        }
      }
    }

    return result;
  }

  return function (iterable, limit) {
    if (Array.isArray(iterable)) {
      return iterable;
    }
    if (Symbol.iterator in Object(iterable)) {
      return sliceIterator(iterable, limit);
    }
    throw new TypeError("Invalid attempt to destructure non-iterable instance");
  };
})();

function stringToBytes(input) {
  const encoded = window.encodeURIComponent(input);
  const result = [];

  for (let index = 0, length = encoded.length; index < length; index++) {
    if (encoded.charAt(index) === "%") {
      if (index + 2 < length) {
        const hexByte = "" + encoded.charAt(++index) + encoded.charAt(++index);
        result.push(hexStringToBytes(hexByte)[0]);
      }
    } else {
      result.push(toSignedByte(encoded.charCodeAt(index)));
    }
  }
  return result;
}

function hexStringToBytes(hexString) {
  hexString = "" + hexString;
  const result = [];
  const safeWindowContext = getSafeWindowContext();
  const safeGlobal = safeWindowContext.safeGlobal;
  let hexIndex = 0;

  for (let byteIndex = 0, byteCount = hexString.length / 2; byteIndex < byteCount; byteIndex++) {
    const highNibble = safeGlobal.parseInt(hexString.charAt(hexIndex++), 16) << 4;
    const lowNibble = safeGlobal.parseInt(hexString.charAt(hexIndex++), 16);
    result[byteIndex] = toSignedByte(highNibble + lowNibble);
  }
  return result;
}
function toSignedByte(value) {
  if (value < -128) {
    return toSignedByte(256 + value);
  }
  if (value > 127) {
    return toSignedByte(value - 256);
  }
  return value;
}

function random4Bytes() {
  const result = [];
  for (let index = 0; index < 4; index++) {
    result[index] = toByte(Math.floor(Math.random() * 256));
  }
  return result;
}

function toByte(value) {
  if (value < -128) {
    return toSignedByte(256 + value);
  }
  if (value > 127) {
    return toSignedByte(value - 256);
  }
  return value;
}

function normalizeTo64Bytes(bytes) {
  const result = [];
  if (!bytes.length) {
    return paddingArrayZero(64);
  }
  if (bytes.length >= 64) {
    return bytes.splice(0, 64);
  }
  for (let index = 0; index < 64; index++) {
    result[index] = bytes[index % bytes.length];
  }
  return result;
}

function xors(leftBytes = [], rightBytes = []) {
  const result = [];
  const rightLength = rightBytes.length;
  for (let index = 0, leftLength = leftBytes.length; index < leftLength; index++) {
    result[index] = xorByte(leftBytes[index], rightBytes[index % rightLength]);
  }
  return result;
}
function xorByte(leftByte, rightByte) {
  return toSignedByte(toSignedByte(leftByte) ^ toSignedByte(rightByte));
}

function genCrc32(bytes) {
  const crcTable = [
    0, 1996959894, 3993919788, 2567524794, 124634137, 1886057615, 3915621685, 2657392035, 249268274, 2044508324, 3772115230, 2547177864, 162941995,
    2125561021, 3887607047, 2428444049, 498536548, 1789927666, 4089016648, 2227061214, 450548861, 1843258603, 4107580753, 2211677639, 325883990,
    1684777152, 4251122042, 2321926636, 335633487, 1661365465, 4195302755, 2366115317, 997073096, 1281953886, 3579855332, 2724688242, 1006888145,
    1258607687, 3524101629, 2768942443, 901097722, 1119000684, 3686517206, 2898065728, 853044451, 1172266101, 3705015759, 2882616665, 651767980,
    1373503546, 3369554304, 3218104598, 565507253, 1454621731, 3485111705, 3099436303, 671266974, 1594198024, 3322730930, 2970347812, 795835527,
    1483230225, 3244367275, 3060149565, 1994146192, 31158534, 2563907772, 4023717930, 1907459465, 112637215, 2680153253, 3904427059, 2013776290,
    251722036, 2517215374, 3775830040, 2137656763, 141376813, 2439277719, 3865271297, 1802195444, 476864866, 2238001368, 4066508878, 1812370925,
    453092731, 2181625025, 4111451223, 1706088902, 314042704, 2344532202, 4240017532, 1658658271, 366619977, 2362670323, 4224994405, 1303535960,
    984961486, 2747007092, 3569037538, 1256170817, 1037604311, 2765210733, 3554079995, 1131014506, 879679996, 2909243462, 3663771856, 1141124467,
    855842277, 2852801631, 3708648649, 1342533948, 654459306, 3188396048, 3373015174, 1466479909, 544179635, 3110523913, 3462522015, 1591671054,
    702138776, 2966460450, 3352799412, 1504918807, 783551873, 3082640443, 3233442989, 3988292384, 2596254646, 62317068, 1957810842, 3939845945,
    2647816111, 81470997, 1943803523, 3814918930, 2489596804, 225274430, 2053790376, 3826175755, 2466906013, 167816743, 2097651377, 4027552580,
    2265490386, 503444072, 1762050814, 4150417245, 2154129355, 426522225, 1852507879, 4275313526, 2312317920, 282753626, 1742555852, 4189708143,
    2394877945, 397917763, 1622183637, 3604390888, 2714866558, 953729732, 1340076626, 3518719985, 2797360999, 1068828381, 1219638859, 3624741850,
    2936675148, 906185462, 1090812512, 3747672003, 2825379669, 829329135, 1181335161, 3412177804, 3160834842, 628085408, 1382605366, 3423369109,
    3138078467, 570562233, 1426400815, 3317316542, 2998733608, 733239954, 1555261956, 3268935591, 3050360625, 752459403, 1541320221, 2607071920,
    3965973030, 1969922972, 40735498, 2617837225, 3943577151, 1913087877, 83908371, 2512341634, 3803740692, 2075208622, 213261112, 2463272603,
    3855990285, 2094854071, 198958881, 2262029012, 4057260610, 1759359992, 534414190, 2176718541, 4139329115, 1873836001, 414664567, 2282248934,
    4279200368, 1711684554, 285281116, 2405801727, 4167216745, 1634467795, 376229701, 2685067896, 3608007406, 1308918612, 956543938, 2808555105,
    3495958263, 1231636301, 1047427035, 2932959818, 3654703836, 1088359270, 936918000, 2847714899, 3736837829, 1202900863, 817233897, 3183342108,
    3401237130, 1404277552, 615818150, 3134207493, 3453421203, 1423857449, 601450431, 3009837614, 3294710456, 1567103746, 711928724, 3020668471,
    3272380065, 1510334235, 755167117,
  ];
  let crc = 4294967295;

  for (let index = 0, length = bytes.length; index < length; index++) {
    crc = (crc >>> 8) ^ crcTable[(crc ^ bytes[index]) & 255];
  }

  return intToHexString(crc ^ -1);
}

function intToHexString(value) {
  return bytesToHexString(intToBytes(value));
}

function bytesToHexString(bytes) {
  return bytes
    .map(function (byteValue) {
      return byteToHex(byteValue);
    })
    .join("");
}

function intToBytes(value) {
  const bytes = [];
  bytes[0] = toSignedByte((value >>> 24) & 255);
  bytes[1] = toSignedByte((value >>> 16) & 255);
  bytes[2] = toSignedByte((value >>> 8) & 255);
  bytes[3] = toSignedByte(value & 255);
  return bytes;
}

function byteToHex(byteValue) {
  const hexChars = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "a", "b", "c", "d", "e", "f"];
  return "" + hexChars[(byteValue >>> 4) & 15] + hexChars[byteValue & 15];
}

function padBytesWithLength(bytes) {
  if (!bytes.length) {
    return paddingArrayZero(64);
  }

  const padded = [];
  const originalLength = bytes.length;
  const zeroPaddingLength = originalLength % 64 <= 60 ? 64 - (originalLength % 64) - 4 : 128 - (originalLength % 64) - 4;

  copyToBytes(bytes, 0, padded, 0, originalLength);
  for (let index = 0; index < zeroPaddingLength; index++) {
    padded[originalLength + index] = 0;
  }
  copyToBytes(intToBytes(originalLength), 0, padded, originalLength + zeroPaddingLength, 4);
  return padded;
}

function cloneArray(arrayLike) {
  if (Array.isArray(arrayLike)) {
    const copy = Array(arrayLike.length);
    for (let index = 0; index < arrayLike.length; index++) {
      copy[index] = arrayLike[index];
    }
    return copy;
  }
  return Array.from(arrayLike);
}

function copyToBytes(sourceBytes, sourceOffset, targetBytes, targetOffset, copyLength) {
  let index = 0;
  const sourceLength = sourceBytes.length;
  for (; index < copyLength; index++) {
    if (sourceOffset + index < sourceLength) {
      targetBytes[targetOffset + index] = sourceBytes[sourceOffset + index];
    }
  }
  return targetBytes;
}

function splitInto64ByteBlocks(bytes) {
  if (bytes.length % 64 !== 0) {
    return [];
  }

  const blocks = [];
  const blockCount = bytes.length / 64;
  let sourceIndex = 0;

  for (let blockIndex = 0; blockIndex < blockCount; blockIndex++) {
    blocks[blockIndex] = [];
    for (let innerIndex = 0; innerIndex < 64; innerIndex++) {
      blocks[blockIndex][innerIndex] = bytes[sourceIndex++];
    }
  }
  return blocks;
}

function applyRoundOperations(blockBytes) {
  const roundHandlers = [
    keepBytesIfKeyValid,
    xorWithFixedKey,
    shiftWithFixedKey,
    xorWithIncreasingKey,
    shiftWithIncreasingKey,
    xorWithDecreasingKey,
    shiftWithDecreasingKey,
  ];

  let roundKeyIndex = 0;
  for (const roundKeyLength = ROUND_KEY_HEX.length; roundKeyIndex < roundKeyLength; ) {
    const roundKeyPair = ROUND_KEY_HEX.substring(roundKeyIndex, roundKeyIndex + 4);
    const operationIndex = hexToByte(roundKeyPair.substring(0, 2));
    const operationKey = hexToByte(roundKeyPair.substring(2, 4));
    blockBytes = roundHandlers[operationIndex](blockBytes, operationKey);
    roundKeyIndex += 4;
  }

  return blockBytes;
}

function keepBytesIfKeyValid(bytes, keyByte = 0) {
  if (keyByte + 256 >= 0) {
    return bytes;
  }
  return [];
}

function xorWithFixedKey(bytes, keyByte) {
  if (!bytes.length) {
    return [];
  }
  keyByte = toByte(keyByte);

  const result = [];
  for (let index = 0, length = bytes.length; index < length; index++) {
    result.push(xor(bytes[index], keyByte));
  }
  return result;
}

function shiftWithFixedKey(bytes, shiftKey) {
  if (!bytes.length) {
    return [];
  }
  shiftKey = toByte(shiftKey);

  const result = [];
  for (let index = 0, length = bytes.length; index < length; index++) {
    result.push(shiftByte(bytes[index], shiftKey));
  }
  return result;
}

function xorWithIncreasingKey(bytes, startKey) {
  if (!bytes.length) {
    return [];
  }
  startKey = toByte(startKey);

  const result = [];
  for (let index = 0, length = bytes.length; index < length; index++) {
    result.push(xorByte(bytes[index], startKey++));
  }
  return result;
}

function shiftWithIncreasingKey(bytes, startKey) {
  if (!bytes.length) {
    return [];
  }
  startKey = toByte(startKey);

  const result = [];
  for (let index = 0, length = bytes.length; index < length; index++) {
    result.push(shift(bytes[index], startKey++));
  }
  return result;
}

function xorWithDecreasingKey(bytes, startKey) {
  if (!bytes.length) {
    return [];
  }
  startKey = toByte(startKey);

  const result = [];
  for (let index = 0, length = bytes.length; index < length; index++) {
    result.push(xorByte(bytes[index], startKey--));
  }
  return result;
}

function shiftWithDecreasingKey(bytes, startKey) {
  if (!bytes.length) {
    return [];
  }
  startKey = toByte(startKey);

  const result = [];
  for (let index = 0, length = bytes.length; index < length; index++) {
    result.push(shiftByte(bytes[index], startKey--));
  }
  return result;
}

function shiftByte(byteValue, delta) {
  return toSignedByte(byteValue + delta);
}

function shiftBytes(bytes = [], offsets = []) {
  const result = [];
  const offsetsLength = offsets.length;
  for (let index = 0, bytesLength = bytes.length; index < bytesLength; index++) {
    result[index] = shiftByte(bytes[index], offsets[index % offsetsLength]);
  }
  return result;
}
function getSafeWindowContext() {
  const SAFE_IFRAME_ID = "NECaptchaSafeWindow";

  function ensureSafeGlobal(candidateWindow, fallbackWindow = window) {
    if (candidateWindow && typeof candidateWindow.parseInt === "function") {
      return candidateWindow;
    }
    return fallbackWindow;
  }

  function destroySafeWindow() {
    let iframe = document.getElementById(SAFE_IFRAME_ID);
    if (iframe) {
      document.body.removeChild(iframe);
      iframe = null;
    }
  }

  const existingIframe = document.getElementById(SAFE_IFRAME_ID);
  if (existingIframe) {
    const safeGlobal = ensureSafeGlobal(existingIframe.contentWindow);
    return {
      safeGlobal,
      destroy: destroySafeWindow,
    };
  }

  let iframeWindow = null;
  try {
    const iframe = document.createElement("iframe");
    iframe.setAttribute("id", SAFE_IFRAME_ID);
    iframe.style.display = "none";
    document.body.appendChild(iframe);
    iframeWindow = iframe.contentWindow;
  } catch (error) {}

  const safeGlobal = ensureSafeGlobal(iframeWindow);
  return {
    safeGlobal,
    destroy: destroySafeWindow,
  };
}

function hexToByte(hexPair) {
  hexPair = "" + hexPair;
  const safeWindowContext = getSafeWindowContext();
  const safeGlobal = safeWindowContext.safeGlobal;
  const highNibble = safeGlobal.parseInt(hexPair.charAt(0), 16) << 4;
  const lowNibble = safeGlobal.parseInt(hexPair.charAt(1), 16);
  return toSignedByte(highNibble + lowNibble);
}

// ============================58=========================
function encodeBase64Chunk(chunkBytes, alphabet, paddingChar) {
  let byte1;
  let byte2;
  let byte3;
  const result = [];

  switch (chunkBytes.length) {
    case 1:
      byte1 = chunkBytes[0];
      byte2 = byte3 = 0;
      result.push(alphabet[(byte1 >>> 2) & 63], alphabet[((byte1 << 4) & 48) + ((byte2 >>> 4) & 15)], paddingChar, paddingChar);
      break;
    case 2:
      byte1 = chunkBytes[0];
      byte2 = chunkBytes[1];
      byte3 = 0;
      result.push(
        alphabet[(byte1 >>> 2) & 63],
        alphabet[((byte1 << 4) & 48) + ((byte2 >>> 4) & 15)],
        alphabet[((byte2 << 2) & 60) + ((byte3 >>> 6) & 3)],
        paddingChar,
      );
      break;
    case 3:
      byte1 = chunkBytes[0];
      byte2 = chunkBytes[1];
      byte3 = chunkBytes[2];
      result.push(
        alphabet[(byte1 >>> 2) & 63],
        alphabet[((byte1 << 4) & 48) + ((byte2 >>> 4) & 15)],
        alphabet[((byte2 << 2) & 60) + ((byte3 >>> 6) & 3)],
        alphabet[byte3 & 63],
      );
      break;
    default:
      return "";
  }

  return result.join("");
}

function encodeBase64(bytes, alphabet, paddingChar) {
  if (!bytes || bytes.length === 0) {
    return "";
  }

  try {
    let offset = 0;
    const encodedChunks = [];

    for (; offset < bytes.length; ) {
      if (!(offset + 3 <= bytes.length)) {
        const tailChunk = bytes.slice(offset);
        encodedChunks.push(encodeBase64Chunk(tailChunk, alphabet, paddingChar));
        break;
      }

      const chunk = bytes.slice(offset, offset + 3);
      encodedChunks.push(encodeBase64Chunk(chunk, alphabet, paddingChar));
      offset += 3;
    }

    return encodedChunks.join("");
  } catch (error) {
    return "";
  }
}

function decodeBase64Chunk(indices) {
  const result = [];

  switch (indices.length) {
    case 2:
      result.push(toByte(((indices[0] << 2) & 255) + ((indices[1] >>> 4) & 3)));
      break;
    case 3:
      result.push(toByte(((indices[0] << 2) & 255) + ((indices[1] >>> 4) & 3)));
      result.push(toByte(((indices[1] << 4) & 255) + ((indices[2] >>> 2) & 15)));
      break;
    case 4:
      result.push(toByte(((indices[0] << 2) & 255) + ((indices[1] >>> 4) & 3)));
      result.push(toByte(((indices[1] << 4) & 255) + ((indices[2] >>> 2) & 15)));
      result.push(toByte(((indices[2] << 6) & 255) + (indices[3] & 63)));
      break;
  }

  return result;
}

function decodeBase64(encodedText, alphabet, paddingChar) {
  function getAlphabetIndex(char) {
    return alphabet.indexOf(char);
  }

  let offset = 0;
  let result = [];
  const paddingIndex = encodedText.indexOf(paddingChar);
  const chars = paddingIndex !== -1 ? encodedText.substring(0, paddingIndex).split("") : encodedText.split("");

  for (let length = chars.length; offset < length; ) {
    if (!(offset + 4 <= length)) {
      const tailIndices = chars.slice(offset).map(getAlphabetIndex);
      result = result.concat(decodeBase64Chunk(tailIndices));
      break;
    }

    const chunkIndices = chars.slice(offset, offset + 4).map(getAlphabetIndex);
    result = result.concat(decodeBase64Chunk(chunkIndices));
    offset += 4;
  }

  return result;
}

function base64Encode(bytes) {
  const privateAlphabet = [
    "i",
    "/",
    "x",
    "1",
    "X",
    "g",
    "U",
    "0",
    "z",
    "7",
    "k",
    "8",
    "N",
    "+",
    "l",
    "C",
    "p",
    "O",
    "n",
    "P",
    "r",
    "v",
    "6",
    "\\",
    "q",
    "u",
    "2",
    "G",
    "j",
    "9",
    "H",
    "R",
    "c",
    "w",
    "T",
    "Y",
    "Z",
    "4",
    "b",
    "f",
    "S",
    "J",
    "B",
    "h",
    "a",
    "W",
    "s",
    "t",
    "A",
    "e",
    "o",
    "M",
    "I",
    "E",
    "Q",
    "5",
    "m",
    "D",
    "d",
    "V",
    "F",
    "L",
    "K",
    "y",
  ];
  const privatePadding = "3";
  return encodeBase64(bytes, privateAlphabet, privatePadding);
}

function xorEncodeWithToken(plainText, xorKey) {
  const keyBytes = stringToBytes(xorKey);
  const plainTextBytes = stringToBytes(plainText);
  return base64Encode(xors(keyBytes, plainTextBytes));
}

function base64Decode(encodedText) {
  const privateAlphabet = [
    "i",
    "/",
    "x",
    "1",
    "X",
    "g",
    "U",
    "0",
    "z",
    "7",
    "k",
    "8",
    "N",
    "+",
    "l",
    "C",
    "p",
    "O",
    "n",
    "P",
    "r",
    "v",
    "6",
    "\\",
    "q",
    "u",
    "2",
    "G",
    "j",
    "9",
    "H",
    "R",
    "c",
    "w",
    "T",
    "Y",
    "Z",
    "4",
    "b",
    "f",
    "S",
    "J",
    "B",
    "h",
    "a",
    "W",
    "s",
    "t",
    "A",
    "e",
    "o",
    "M",
    "I",
    "E",
    "Q",
    "5",
    "m",
    "D",
    "d",
    "V",
    "F",
    "L",
    "K",
    "y",
  ];
  const privatePadding = "3";
  return decodeBase64(encodedText, privateAlphabet, privatePadding);
}

function base64EncodeWithCustomAlphabet(bytes, alphabet, paddingChar) {
  const finalAlphabet = alphabet !== undefined && alphabet !== null ? alphabet : DEFAULT_BASE64_ALPHABET;
  const finalPadding = paddingChar !== undefined && paddingChar !== null ? paddingChar : DEFAULT_BASE64_PADDING;
  return encodeBase64(bytes, finalAlphabet.split(""), finalPadding);
}

// ============================滑动指纹=============================
function randint(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function choice(items) {
  return items[randint(0, items.length - 1)];
}

function weightedChoice(items, weights) {
  const total = weights.reduce((sum, value) => sum + value, 0);
  let threshold = Math.random() * total;

  for (let index = 0; index < items.length; index += 1) {
    threshold -= weights[index];
    if (threshold < 0) {
      return items[index];
    }
  }

  return items[items.length - 1];
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function maybe(probability) {
  return Math.random() < probability;
}

function interpolate(points, ratio) {
  for (let index = 1; index < points.length; index += 1) {
    const [leftX, leftY] = points[index - 1];
    const [rightX, rightY] = points[index];

    if (ratio <= rightX) {
      const width = rightX - leftX || 1;
      const localRatio = clamp((ratio - leftX) / width, 0, 1);
      return leftY + (rightY - leftY) * localRatio;
    }
  }

  return points[points.length - 1][1];
}

function createStartTime() {
  const band = weightedChoice(["fast", "normal", "slow"], [2, 4, 2]);

  if (band === "fast") {
    return randint(27, 45);
  }

  if (band === "normal") {
    return randint(46, 70);
  }

  return randint(71, 95);
}

function createYProfile(dis) {
  const mode = weightedChoice(["flat", "rise", "dip"], dis >= 180 ? [2, 5, 1] : [3, 4, 2]);

  if (mode === "flat") {
    const peak = weightedChoice([0, 1, 2], [5, 3, 1]);
    const settle = peak === 0 ? 0 : choice([peak, peak - 1]);

    return {
      min: 0,
      max: Math.max(peak, settle),
      points: [
        [0, 0],
        [randint(35, 55) / 100, peak],
        [randint(80, 92) / 100, settle],
        [1, settle],
      ],
    };
  }

  if (mode === "rise") {
    const peak = dis >= 220 ? randint(5, 7) : dis >= 160 ? randint(3, 5) : randint(1, 3);
    const settle = Math.max(0, peak - randint(0, Math.min(2, peak)));

    return {
      min: 0,
      max: peak,
      points: [
        [0, 0],
        [randint(35, 60) / 100, Math.max(1, Math.round(peak * 0.5))],
        [randint(60, 82) / 100, peak],
        [randint(86, 95) / 100, settle],
        [1, settle],
      ],
    };
  }

  const dip = -randint(1, dis >= 140 ? 2 : 1);
  const settle = choice([dip, 0]);

  return {
    min: dip,
    max: 0,
    points: [
      [0, 0],
      [randint(35, 55) / 100, dip],
      [randint(72, 88) / 100, dip],
      [randint(88, 97) / 100, settle],
      [1, settle],
    ],
  };
}

function createProfile(dis) {
  const stride = weightedChoice(
    ["steady", "balanced", "burst"],
    dis <= 135 ? [7, 3, 1] : dis >= 200 ? [1, 4, 4] : dis >= 150 ? [2, 5, 3] : [3, 5, 2],
  );

  const correctionChance = dis >= 110 && dis <= 124 ? 0.24 : dis >= 125 && dis <= 140 ? 0.07 : dis > 140 ? 0.14 : 0;
  const correctionEnabled = maybe(correctionChance);
  const overshoot = correctionEnabled ? randint(1, Math.min(3, Math.max(1, Math.round(dis * 0.02)))) : 0;
  const rebound = correctionEnabled ? randint(2, Math.min(8, Math.max(3, Math.round(dis * 0.05)))) : 0;
  const bigPauseBand = weightedChoice(["none", "mid", "long", "huge"], dis >= 180 ? [0, 4, 4, 1] : [1, 4, 4, 1]);

  let bigPause = 0;
  if (bigPauseBand === "mid") {
    bigPause = randint(40, 90);
  } else if (bigPauseBand === "long") {
    bigPause = randint(100, 220);
  } else if (bigPauseBand === "huge") {
    bigPause = dis >= 180 ? randint(240, 650) : randint(220, 380);
  }

  return {
    startTime: createStartTime(),
    startHoldCount: weightedChoice([0, 1, 2], [4, 4, 1]),
    stride,
    maxStepCap:
      dis <= 120
        ? weightedChoice([3, 4], [3, 2])
        : dis <= 140
          ? weightedChoice([2, 3], [4, 1])
          : dis <= 190
            ? weightedChoice([3, 4], [3, 2])
            : weightedChoice([4, 5, 6], [2, 4, 1]),
    yProfile: createYProfile(dis),
    shortPauseBudget: dis >= 170 ? randint(4, 6) : randint(2, 4),
    longPauseBudget: dis >= 170 ? randint(2, 4) : randint(1, 3),
    bigPause,
    correctionEnabled,
    overshoot,
    rebound,
  };
}

function updateY(currentY, ratio, yProfile) {
  const targetY = Math.round(interpolate(yProfile.points, ratio));

  if (currentY !== targetY) {
    const distance = Math.abs(targetY - currentY);
    const moveChance = distance >= 2 ? 0.45 : 0.16;

    if (maybe(moveChance)) {
      currentY += Math.sign(targetY - currentY);
    }
  }

  return clamp(currentY, yProfile.min, yProfile.max);
}

function pickForwardStep(distanceLeft, ratio, profile, phase) {
  let items;
  let weights;

  if (phase === "settle") {
    items = [0, 1, 2];
    weights = [2, 7, 1];
  } else if (ratio < 0.12) {
    if (profile.stride === "steady") {
      items = [0, 1, 2];
      weights = [1, 8, 3];
    } else if (profile.stride === "balanced") {
      items = [0, 1, 2, 3];
      weights = [1, 7, 4, 1];
    } else {
      items = [0, 1, 2, 3, 4];
      weights = [1, 5, 4, 2, 1];
    }
  } else if (ratio < 0.58) {
    if (profile.stride === "steady") {
      items = [0, 1, 2, 3];
      weights = [1, 4, 7, 1];
    } else if (profile.stride === "balanced") {
      items = [0, 1, 2, 3, 4];
      weights = [1, 3, 5, 4, 1];
    } else {
      items = [0, 1, 2, 3, 4, 5];
      weights = [1, 3, 4, 4, 2, 1];
    }
  } else if (ratio < 0.84) {
    if (profile.stride === "steady") {
      items = [0, 1, 2];
      weights = [1, 7, 2];
    } else if (profile.stride === "balanced") {
      items = [0, 1, 2, 3];
      weights = [1, 5, 4, 1];
    } else {
      items = [0, 1, 2, 3, 4];
      weights = [1, 4, 4, 2, 1];
    }
  } else {
    items = [0, 1, 2];
    weights = [2, 8, 1];
  }

  let step = weightedChoice(items, weights);

  if (profile.stride === "burst" && profile.maxStepCap > 3 && ratio > 0.2 && ratio < 0.7 && distanceLeft > 30 && maybe(0.07)) {
    step += randint(1, distanceLeft > 90 ? 2 : 1);
  }

  return Math.min(step, distanceLeft, profile.maxStepCap);
}

function pickBackwardStep(distanceLeft) {
  const step = weightedChoice([0, 1, 2, 3], [1, 6, 3, 1]);
  return Math.min(step, distanceLeft);
}

function pickTimeStep(ratio, xStep, profile, phase) {
  let items;
  let weights;

  if (phase === "backtrack") {
    items = [4, 6, 8, 10, 12, 15, 18];
    weights = [1, 3, 4, 3, 2, 1, 1];
  } else if (phase === "settle") {
    items = [2, 3, 4, 5, 6, 8, 10, 12];
    weights = [2, 4, 4, 3, 2, 1, 1, 1];
  } else if (ratio < 0.2) {
    items = [1, 2, 3, 4, 5];
    weights = [3, 5, 5, 3, 1];
  } else if (ratio < 0.75) {
    items = [1, 2, 3, 4, 5, 6, 8];
    weights = [3, 5, 5, 4, 2, 1, 1];
  } else if (ratio < 0.9) {
    items = [1, 2, 3, 4, 5, 6, 8, 10, 12];
    weights = [1, 4, 5, 4, 3, 2, 1, 1, 1];
  } else {
    items = [2, 3, 4, 5, 6, 8, 10, 12, 15];
    weights = [3, 4, 4, 3, 2, 2, 1, 1, 1];
  }

  let tStep = weightedChoice(items, weights);

  if (xStep === 0) {
    tStep += randint(1, 5);
  }

  if (ratio > 0.68 && profile.shortPauseBudget > 0 && maybe(xStep === 0 ? 0.22 : 0.07)) {
    tStep += randint(6, ratio > 0.9 ? 24 : 14);
    profile.shortPauseBudget -= 1;
  }

  if (ratio > 0.84 && profile.longPauseBudget > 0 && maybe(0.08)) {
    tStep += randint(25, ratio > 0.95 ? 90 : 60);
    profile.longPauseBudget -= 1;
  }

  if (ratio > 0.9 && profile.bigPause > 0 && maybe(0.06)) {
    tStep += profile.bigPause;
    profile.bigPause = 0;
  }

  return tStep;
}

function pushPoint(track, state) {
  track.push([state.x, state.y, state.t, 1]);
}

function runSegment(track, state, finalDis, targetX, direction, profile, phase) {
  let zeroStreak = 0;

  while ((direction > 0 && state.x < targetX) || (direction < 0 && state.x > targetX)) {
    const distanceLeft = Math.abs(targetX - state.x);
    const ratio = finalDis === 0 ? 1 : clamp(state.x / finalDis, 0, 1.2);
    const stepSize = direction > 0 ? pickForwardStep(distanceLeft, ratio, profile, phase) : pickBackwardStep(distanceLeft);

    let appliedStep = stepSize;
    if (appliedStep === 0) {
      zeroStreak += 1;
      if (zeroStreak > 2 && distanceLeft > 0) {
        appliedStep = 1;
      }
    } else {
      zeroStreak = 0;
    }

    const xStep = direction * Math.min(appliedStep, distanceLeft);
    state.x += xStep;
    state.y = updateY(state.y, clamp(state.x / finalDis, 0, 1), profile.yProfile);
    state.t += pickTimeStep(ratio, xStep, profile, phase);
    pushPoint(track, state);
  }
}

function addTail(track, state, profile, finalDis) {
  const holdCount = weightedChoice([1, 2, 3], [2, 4, 2]);

  for (let index = 0; index < holdCount; index += 1) {
    let tStep = weightedChoice([0, 2, 4, 6, 8, 12, 16], [1, 2, 3, 3, 2, 2, 1]);

    if (profile.bigPause > 0 && (index === holdCount - 1 || maybe(0.4))) {
      tStep += profile.bigPause;
      profile.bigPause = 0;
    } else if (maybe(0.3)) {
      tStep += randint(20, 80);
    }

    state.t += tStep;
    state.y = updateY(state.y, 1, profile.yProfile);
    state.x = finalDis;
    pushPoint(track, state);
  }
}

function normalizeTrackOptions(options = {}) {
  return {
    width: Math.max(1, Number(options.width) || DEFAULT_CAPTCHA_WIDTH),
    sliderWidth: Math.max(1, Number(options.sliderWidth) || DEFAULT_SLIDER_WIDTH),
    jigsawWidth: Math.max(1, Number(options.jigsawWidth) || DEFAULT_JIGSAW_WIDTH),
    startLeft: Math.max(0, Number(options.startLeft) || DEFAULT_START_LEFT),
  };
}

function restrictLeftBySourceContract(dragX, trackOptions, elementWidth, relativeOffset) {
  const { startLeft, width, sliderWidth } = trackOptions;
  const maxLeft = width - elementWidth;
  let currentLeft = startLeft + dragX;

  if (relativeOffset !== undefined && relativeOffset !== null) {
    const boundaryGuard = relativeOffset < 0 ? -relativeOffset : relativeOffset / 2;

    if (dragX <= boundaryGuard) {
      const overflow = dragX;
      const adjust = relativeOffset < 0 ? -overflow / 2 : overflow;
      currentLeft += adjust;
    } else if (width - dragX - sliderWidth <= boundaryGuard) {
      const overflow = dragX - (width - sliderWidth - boundaryGuard);
      const adjust = relativeOffset < 0 ? -overflow / 2 : overflow;
      currentLeft += relativeOffset / 2 + adjust;
    } else {
      currentLeft += relativeOffset / 2;
    }
  }

  return clamp(currentLeft, startLeft, maxLeft);
}

function computeJigsawLeftFromDragX(dragX, trackOptions) {
  return restrictLeftBySourceContract(
    dragX,
    trackOptions,
    trackOptions.jigsawWidth,
    trackOptions.sliderWidth - trackOptions.jigsawWidth,
  );
}

function resolveDragDistanceForJigsawLeft(targetJigsawLeft, trackOptions) {
  const maxSliderLeft = Math.max(trackOptions.startLeft, trackOptions.width - trackOptions.sliderWidth);
  const desiredLeft = clamp(targetJigsawLeft, trackOptions.startLeft, trackOptions.width - trackOptions.jigsawWidth);
  const preferredLeft = Math.min(desiredLeft + 0.5, trackOptions.width - trackOptions.jigsawWidth);

  let low = trackOptions.startLeft;
  let high = maxSliderLeft;

  for (let index = 0; index < 40; index += 1) {
    const middle = (low + high) / 2;
    const middleLeft = computeJigsawLeftFromDragX(middle, trackOptions);

    if (middleLeft < preferredLeft) {
      low = middle;
    } else {
      high = middle;
    }
  }

  const candidateSet = new Set([
    Math.floor(low),
    Math.ceil(low),
    Math.floor(high),
    Math.ceil(high),
    Math.floor((low + high) / 2),
    Math.ceil((low + high) / 2),
  ]);

  let bestCandidate = trackOptions.startLeft;
  let bestLeft = computeJigsawLeftFromDragX(bestCandidate, trackOptions);

  candidateSet.forEach(function (candidate) {
    const normalizedCandidate = clamp(candidate, trackOptions.startLeft, maxSliderLeft);
    const candidateLeft = computeJigsawLeftFromDragX(normalizedCandidate, trackOptions);
    const candidateParseDiff = Math.abs(Math.trunc(candidateLeft) - desiredLeft);
    const bestParseDiff = Math.abs(Math.trunc(bestLeft) - desiredLeft);

    if (candidateParseDiff < bestParseDiff) {
      bestCandidate = normalizedCandidate;
      bestLeft = candidateLeft;
      return;
    }

    if (candidateParseDiff > bestParseDiff) {
      return;
    }

    const candidateDistance = Math.abs(candidateLeft - preferredLeft);
    const bestDistance = Math.abs(bestLeft - preferredLeft);

    if (candidateDistance < bestDistance || (candidateDistance === bestDistance && normalizedCandidate < bestCandidate)) {
      bestCandidate = normalizedCandidate;
      bestLeft = candidateLeft;
    }
  });

  return bestCandidate;
}

function getTrack(dis = 0, options = {}) {
  const trackOptions = normalizeTrackOptions(options);
  const targetJigsawLeft = Math.max(0, Number.parseInt(dis, 10) || 0);
  const distance = resolveDragDistanceForJigsawLeft(targetJigsawLeft, trackOptions);
  const finalJigsawLeft = computeJigsawLeftFromDragX(distance, trackOptions);

  if (distance === 0) {
    return {
      track: [],
      dis: 0,
      width: trackOptions.width,
      jigsawLeft: finalJigsawLeft,
      targetJigsawLeft,
    };
  }

  const profile = createProfile(distance);
  const track = [];
  const state = {
    x: Math.min(distance, 4),
    y: 0,
    t: profile.startTime,
  };

  pushPoint(track, state);

  for (let index = 0; index < profile.startHoldCount; index += 1) {
    state.t += randint(2, 4);
    pushPoint(track, state);
  }

  if (distance <= 4) {
    addTail(track, state, profile, distance);
    return {
      track,
      dis: distance,
      width: trackOptions.width,
      jigsawLeft: finalJigsawLeft,
      targetJigsawLeft,
    };
  }

  if (profile.correctionEnabled) {
    const forwardTarget = distance + profile.overshoot;
    const backtrackTarget = Math.max(4, distance - profile.rebound);

    runSegment(track, state, distance, forwardTarget, 1, profile, "forward");

    state.t += weightedChoice([6, 10, 14, 20], [3, 3, 2, 1]);
    pushPoint(track, state);

    runSegment(track, state, distance, backtrackTarget, -1, profile, "backtrack");
    runSegment(track, state, distance, distance, 1, profile, "settle");
  } else {
    runSegment(track, state, distance, distance, 1, profile, "forward");
  }

  addTail(track, state, profile, distance);

  return {
    track,
    dis: distance,
    width: trackOptions.width,
    jigsawLeft: finalJigsawLeft,
    targetJigsawLeft,
  };
}

function encodeTracePointWithToken(token, rawTracePoint) {
  const safeToken = token == null ? "" : String(token);
  return xorEncodeWithToken(safeToken, rawTracePoint + "");
}

function standardDeviation(values) {
  const average = mean(values);
  const squaredDistances = [];

  for (let index = 0; index < values.length; index++) {
    const offsetFromMean = values[index] - average;
    squaredDistances.push(Math.pow(offsetFromMean, 2));
  }

  let squaredDistanceSum = 0;
  for (let index = 0; index < squaredDistances.length; index++) {
    if (squaredDistances[index]) {
      squaredDistanceSum += squaredDistances[index];
    }
  }

  return Math.sqrt(squaredDistanceSum / values.length);
}
function roundTo4(value) {
  return parseFloat(value.toFixed(4));
}

function mean(values) {
  let sum = 0;
  for (let index = 0; index < values.length; index++) {
    sum += values[index];
  }
  return sum / values.length;
}

function cloneArrayLike(arrayLike) {
  if (Array.isArray(arrayLike)) {
    const copy = Array(arrayLike.length);
    for (let index = 0; index < arrayLike.length; index++) {
      copy[index] = arrayLike[index];
    }
    return copy;
  }
  return Array.from(arrayLike);
}
function getUniqueValues(values) {
  const uniqueValues = [];
  for (let index = 0; index < values.length; index++) {
    if (uniqueValues.indexOf(values[index]) === -1) {
      uniqueValues.push(values[index]);
    }
  }
  return uniqueValues;
}

function percentile(values, percentileValue) {
  const sorted = values.slice().sort(function sortAscending(left, right) {
    return left - right;
  });

  if (percentileValue <= 0) {
    return sorted[0];
  }
  if (percentileValue >= 100) {
    return sorted[sorted.length - 1];
  }

  const scaledIndex = (sorted.length - 1) * (percentileValue / 100);
  const lowerIndex = Math.floor(scaledIndex);
  const lowerValue = sorted[lowerIndex];
  const upperValue = sorted[lowerIndex + 1];

  return lowerValue + (upperValue - lowerValue) * (scaledIndex - lowerIndex);
}
function differentiateSeries(timeAxis, valueAxis) {
  const deltaTime = [];
  const deltaValue = [];

  for (let index = 0; index < timeAxis.length - 1; index++) {
    deltaTime.push(timeAxis[index + 1] - timeAxis[index]);
    deltaValue.push(valueAxis[index + 1] - valueAxis[index]);
  }

  const derivatives = [];
  for (let index = 0; index < deltaValue.length; index++) {
    derivatives.push(deltaValue[index] / deltaTime[index]);
  }
  return derivatives;
}
function splitTraceColumns(tracePoints = []) {
  const xOffsets = [];
  const yOffsets = [];
  const elapsedTimes = [];

  if (!Array.isArray(tracePoints) || tracePoints.length <= 2) {
    return [xOffsets, yOffsets, elapsedTimes];
  }

  for (let index = 0; index < tracePoints.length; index++) {
    const point = tracePoints[index];
    xOffsets.push(point[0]);
    yOffsets.push(point[1]);
    elapsedTimes.push(point[2]);
  }

  return [xOffsets, yOffsets, elapsedTimes];
}

function computeVelocitySeries(xOffsets, yOffsets, elapsedTimes) {
  const xVelocity = differentiateSeries(elapsedTimes, xOffsets);
  const yVelocity = differentiateSeries(elapsedTimes, yOffsets);
  const radialDistance = [];

  for (let index = 0; index < xOffsets.length; index++) {
    radialDistance.push(Math.sqrt(Math.pow(xOffsets[index], 2) + Math.pow(yOffsets[index], 2)));
  }

  const radialVelocity = differentiateSeries(elapsedTimes, radialDistance);
  return [xVelocity, yVelocity, radialVelocity];
}

function computeAccelerationSeries(xVelocity, yVelocity, radialVelocity, elapsedTimes) {
  const timeAxisForAcceleration = elapsedTimes.slice(0, -1);
  return [
    differentiateSeries(timeAxisForAcceleration, xVelocity),
    differentiateSeries(timeAxisForAcceleration, yVelocity),
    differentiateSeries(timeAxisForAcceleration, radialVelocity),
  ];
}

function summarizeSeries(values) {
  return [
    roundTo4(Math.min.apply(Math, cloneArrayLike(values))),
    roundTo4(Math.max.apply(Math, cloneArrayLike(values))),
    roundTo4(mean(values)),
    roundTo4(standardDeviation(values)),
    getUniqueValues(values).length,
    roundTo4(percentile(values, 25)),
    roundTo4(percentile(values, 75)),
  ];
}

function extractMotionFeatures(tracePoints = []) {
  if (!Array.isArray(tracePoints) || tracePoints.length <= 2) {
    return [];
  }

  const [xOffsets, yOffsets, elapsedTimes] = splitTraceColumns(tracePoints);
  const [xVelocity, yVelocity, radialVelocity] = computeVelocitySeries(xOffsets, yOffsets, elapsedTimes);
  const [xAcceleration, yAcceleration, radialAcceleration] = computeAccelerationSeries(xVelocity, yVelocity, radialVelocity, elapsedTimes);

  return [
    getUniqueValues(xOffsets).length,
    getUniqueValues(yOffsets).length,
    roundTo4(mean(yOffsets)),
    roundTo4(standardDeviation(yOffsets)),
    xOffsets.length,
  ]
    .concat(summarizeSeries(xVelocity))
    .concat(summarizeSeries(yVelocity))
    .concat(summarizeSeries(radialVelocity))
    .concat(summarizeSeries(xAcceleration))
    .concat(summarizeSeries(yAcceleration))
    .concat(summarizeSeries(radialAcceleration));
}

function buildTraceData(token, drag, options = {}) {
  const trackResult = getTrack(drag, options);
  const atomTraceData = trackResult.track.map(function (point) {
    return Array.isArray(point) ? point.slice() : point;
  });
  const traceData = atomTraceData.map(function (point) {
    return encodeTracePointWithToken(token, point);
  });

  // console.log("atomTraceData",JSON.stringify(atomTraceData, null, 2));
  // console.log("traceData",JSON.stringify(traceData, null, 2));
  
  const sampledEncodedTrace = utils.sample(traceData, SAMPLE_COUNT);
  const d = encryptWithAes(sampledEncodedTrace.join(":"));

  const percentLeft = (Math.trunc(trackResult.jigsawLeft) / trackResult.width) * 100;
  const p = encryptWithAes(xorEncodeWithToken(token, percentLeft + ""));
  const deduplicatedTrace = utils.unique2DArray(atomTraceData, 2);
  const motionFeatureVector = extractMotionFeatures(deduplicatedTrace);
  const f = encryptWithAes(xorEncodeWithToken(token, motionFeatureVector.join(",")));
  const ext = encryptWithAes(xorEncodeWithToken(token, "1," + traceData.length));
  return {
    d,
    p,
    f,
    ext,
    dis: trackResult.dis,
  };
}

function normalizeValidateCipher(cipherText) {
  return String(cipherText == null ? "" : cipherText).replace(/[\\/+]/g, function (matched) {
    if (matched === "\\") {
      return "-";
    }
    if (matched === "/") {
      return "_";
    }
    return "*";
  });
}

function buildFinalValidate(serverValidate, fingerprint, zoneId) {
  const validateText = String(serverValidate == null ? "" : serverValidate);
  const fingerprintText = String(fingerprint == null ? "" : fingerprint);
  const zonePrefix = zoneId ? String(zoneId) + "_" : "";
  const encryptedValidate = encryptWithAes(validateText + "::" + fingerprintText);
  return zonePrefix + normalizeValidateCipher(encryptedValidate) + "_v_i_1";
}

module.exports = {
  generateCbValue,
  buildTraceData,
  buildFinalValidate,
  encryptWithAes
};
