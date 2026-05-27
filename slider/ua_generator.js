const crypto = require('crypto');


const ANDROID_VERSIONS = [
    { ver: '7.0',   buildPrefix: ['NRD90M', 'NBD92F', 'N2G47H'] },
    { ver: '7.1.1', buildPrefix: ['NMF26X', 'N6F26Q', 'N4F26I'] },
    { ver: '7.1.2', buildPrefix: ['N2G47O', 'NHG47Q', 'N2G48B'] },
    { ver: '8.0.0', buildPrefix: ['OPR1', 'OPR4', 'OPR6', 'OPD1'] },
    { ver: '8.1.0', buildPrefix: ['OPM1', 'OPM2', 'OPM7', 'OPM8'] },
    { ver: '9',     buildPrefix: ['PPR1', 'PQ1A', 'PQ2A', 'PKQ1'] },
    { ver: '10',    buildPrefix: ['QQ1A', 'QQ2A', 'QQ3A', 'QKQ1'] },
    { ver: '11',    buildPrefix: ['RP1A', 'RKQ1', 'RQ3A'] },
    { ver: '12',    buildPrefix: ['SP1A', 'SKQ1', 'SQ1A'] },
    { ver: '13',    buildPrefix: ['TP1A', 'TKQ1', 'TQ3A'] },
    { ver: '14',    buildPrefix: ['UP1A', 'UKQ1', 'UQ1A'] },
];

const DEVICES = [
    'MI 6', 'MI 8', 'MI 9', 'MI 10', 'MI 11', 'Mi 12', 'Mi 13',
    'Redmi Note 8', 'Redmi Note 9', 'Redmi Note 10', 'Redmi K30', 'Redmi K40',
    'HUAWEI P30', 'HUAWEI P40', 'HUAWEI Mate 30', 'HUAWEI Mate 40',
    'HONOR 20', 'HONOR 30', 'HONOR V30',
    'OPPO R15', 'OPPO R17', 'OPPO Reno', 'OPPO Reno5', 'PCAM00', 'PBEM00',
    'vivo X21', 'vivo X27', 'vivo X50', 'vivo NEX', 'V1962A', 'V2055A',
    'OnePlus 7', 'OnePlus 8', 'OnePlus 9',
    'SM-G9730', 'SM-G9750', 'SM-G9810', 'SM-N9760',
    'Pixel 3', 'Pixel 4', 'Pixel 5', 'Pixel 6',
];

const CHROME_VERSIONS = [
    '69.0.3497.109', '70.0.3538.110', '74.0.3729.157', '78.0.3904.108',
    '83.0.4103.106', '87.0.4280.141', '91.0.4472.120', '95.0.4638.74',
    '99.0.4844.88',  '103.0.5060.71', '107.0.5304.105', '110.0.5481.65',
    '114.0.5735.131','118.0.5993.65', '122.0.6261.119',
];

const APP_VERSIONS = [
    '1.8.5', '1.8.8', '1.9.0', '1.9.3', '1.9.6', '1.9.9', '2.0.0', '2.0.3', '2.1.0',
];

function randInt(min, max) {
    return Math.floor(Math.random() * (max - min + 1)) + min;
}

function pick(arr) {
    return arr[Math.floor(Math.random() * arr.length)];
}


function genBuildId(prefix) {
    const year = randInt(17, 23);
    const month = String(randInt(1, 12)).padStart(2, '0');
    const day = String(randInt(1, 28)).padStart(2, '0');
    const tail = String(randInt(1, 999)).padStart(3, '0');
    return `${prefix}.${year}${month}${day}.${tail}`;
}


function genDeviceId() {
    return crypto.randomBytes(16).toString('hex');
}

function genBsDvid() {
    return crypto.randomBytes(65)
        .toString('base64')
        .replace(/=+$/, '');
}


function generateUA(options = {}) {
    // 选择 Android 版本及对应 build 前缀
    let androidEntry;
    if (options.androidVersion) {
        androidEntry = ANDROID_VERSIONS.find(v => v.ver === options.androidVersion)
            || ANDROID_VERSIONS[ANDROID_VERSIONS.length - 1];
    } else {
        androidEntry = pick(ANDROID_VERSIONS);
    }

    const androidVer  = androidEntry.ver;
    const buildPrefix = pick(androidEntry.buildPrefix);
    const buildId     = genBuildId(buildPrefix);

    const device        = options.device        || pick(DEVICES);
    const chromeVersion = options.chromeVersion || pick(CHROME_VERSIONS);
    const appVersion    = options.appVersion    || pick(APP_VERSIONS);
    const deviceId      = options.deviceId      || genDeviceId();
    const bsDvid        = options.bsDvid        || genBsDvid();

    const ua = `Mozilla/5.0 (Linux; Android ${androidVer}; ${device} Build/${buildId}; wv) `
             + `AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/${chromeVersion} `
             + `Mobile Safari/537.36 moutaiapp/${appVersion} `
             + `device-id/${deviceId} `
             + `BS-DVID/${bsDvid}`;

    return {
        ua,
        deviceId,
        bsDvid,
        parts: {
            androidVersion: androidVer,
            device,
            buildId,
            chromeVersion,
            appVersion,
        },
    };
}

module.exports = {
    generateUA,
    genDeviceId,
    genBsDvid,
};

