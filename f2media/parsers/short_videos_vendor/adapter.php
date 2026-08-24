<?php
declare(strict_types=1);

/*
 * F2Media's local adapter for jiuhunwl/short_videos.
 *
 * The upstream project exposes HTTP endpoints.  F2Media deliberately calls the
 * parser classes directly so no public API is involved and Cookie access stays
 * behind F2Media's two permission gates.
 */

$allowed = ['douyin', 'kuaishou', 'xiaohongshu', 'bilibili'];

function respond(array $payload, int $exitCode = 0): void
{
    $json = json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    if ($json === false) {
        $json = json_encode(['ok' => false, 'error' => 'short_videos adapter JSON 编码失败']);
        $exitCode = 1;
    }
    fwrite(STDOUT, $json . PHP_EOL);
    exit($exitCode);
}

if ($argc > 1 && $argv[1] === '--health') {
    respond([
        'ok' => class_exists('CurlHandle') || function_exists('curl_init'),
        'php_version' => PHP_VERSION,
        'curl' => function_exists('curl_init'),
    ]);
}

$raw = stream_get_contents(STDIN);
$request = json_decode($raw ?: '', true);
if (!is_array($request)) {
    respond(['ok' => false, 'error' => 'short_videos 输入不是 JSON 对象'], 2);
}

$platform = (string)($request['platform'] ?? '');
$url = trim((string)($request['url'] ?? ''));
$cookie = trim((string)($request['cookie'] ?? ''));
if (!in_array($platform, $allowed, true)) {
    respond(['ok' => false, 'error' => 'short_videos 不支持平台: ' . $platform], 2);
}
if ($url === '') {
    respond(['ok' => false, 'error' => 'URL 不能为空'], 2);
}
if (!function_exists('curl_init')) {
    respond(['ok' => false, 'error' => 'PHP cURL 扩展未加载'], 2);
}

$base = __DIR__;
switch ($platform) {
    case 'douyin':
        require_once $base . '/DouyinParser.php';
        $parser = new DouyinParser();
        $parser->setCookie($cookie);
        $encoded = $parser->parse($url);
        break;
    case 'kuaishou':
        require_once $base . '/KuaishouSpider.php';
        $parser = new KuaishouSpider($cookie, 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/143 Safari/537.36', 25);
        $encoded = json_encode($parser->analyze($url), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        break;
    case 'xiaohongshu':
        require_once $base . '/XiaohongshuParser.php';
        $parser = new XiaohongshuParser();
        $parser->setCookie($cookie);
        $encoded = $parser->parse($url);
        break;
    case 'bilibili':
        require_once $base . '/BilibiliParser.php';
        $parser = new BilibiliParser($cookie);
        $encoded = $parser->parse($url);
        break;
    default:
        respond(['ok' => false, 'error' => '未知平台'], 2);
}

$payload = is_string($encoded) ? json_decode($encoded, true) : $encoded;
if (!is_array($payload)) {
    respond(['ok' => false, 'error' => 'short_videos 没有返回 JSON', 'raw_type' => gettype($encoded)], 1);
}

$code = $payload['code'] ?? null;
if ($code !== 200 && $code !== '200') {
    respond([
        'ok' => false,
        'error' => (string)($payload['msg'] ?? 'short_videos 解析失败'),
        'upstream' => $payload,
    ], 1);
}

respond(['ok' => true, 'platform' => $platform, 'data' => $payload['data'] ?? $payload]);
