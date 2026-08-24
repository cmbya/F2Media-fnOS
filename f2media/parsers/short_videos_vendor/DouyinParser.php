<?php
/**
 * @Author: JH-Ahua
 * @CreateTime: 2026/2/12 下午9:47
 * @email: admin@bugpk.com
 * @blog: www.jiuhunwl.cn
 * @Api: api.bugpk.com
 * @tip: 整合视频、图文、图集、实况解析
 */

class DouyinParser
{
    private $headers;
    private $cookie;
    private $userAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';

    public function __construct()
    {
        $this->headers = [
            'User-Agent: ' . $this->userAgent,
            'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language: zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        ];
        // 默认 Cookie，可通过 setCookie 方法覆盖
        $this->cookie = "";
    }

    /**
     * 设置Cookie
     */
    public function setCookie($cookie)
    {
        $this->cookie = $cookie;
    }

    /**
     * 统一输出函数
     */
    private function output($code, $msg, $data = [])
    {
        return json_encode([
            'code' => $code,
            'msg' => $msg,
            'data' => $data
        ], 480);
    }

    /**
     * 发送HTTP请求
     */
    private function request($url, $customHeaders = [], $returnHeader = false)
    {
        $ch = curl_init();
        curl_setopt($ch, CURLOPT_URL, $url);
        curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);
        curl_setopt($ch, CURLOPT_SSL_VERIFYHOST, false);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
        curl_setopt($ch, CURLOPT_ENCODING, 'gzip,deflate');
        curl_setopt($ch, CURLOPT_TIMEOUT, 10);

        // 覆盖同名请求头，避免同时发送两个 User-Agent/Accept/Referer。
        $headers = $this->headers;
        foreach ($customHeaders as $customHeader) {
            $headerName = strtolower(trim(strtok($customHeader, ':')));
            if ($headerName === '') {
                continue;
            }
            $headers = array_values(array_filter($headers, function ($header) use ($headerName) {
                return strtolower(trim(strtok($header, ':'))) !== $headerName;
            }));
        }
        $headers = array_merge($headers, $customHeaders);
        if ($this->cookie) {
            curl_setopt($ch, CURLOPT_COOKIE, $this->cookie);
        }
        curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);

        if ($returnHeader) {
            curl_setopt($ch, CURLOPT_HEADER, true);
            curl_setopt($ch, CURLOPT_NOBODY, true);
        }

        $response = curl_exec($ch);
        $error = curl_error($ch);
        curl_close($ch);

        if ($error) {
            return false;
        }
        return $response;
    }

    /**
     * 获取重定向后的真实链接
     */
    private function getRealUrl($url)
    {
        // 方案一：优先使用 get_headers
        stream_context_set_default([
            'http' => [
                'method' => 'GET',
                'header' => "User-Agent: " . $this->userAgent
            ]
        ]);

        $headers = @get_headers($url, 1);

        if (isset($headers['Location'])) {
            $location = $headers['Location'];
            if (is_array($location)) {
                // 优先寻找包含 video/note/modal_id 等特征的链接
                foreach ($location as $loc) {
                    if ($this->extractId($loc)) {
                        return $loc;
                    }
                }
                return $location[0];
            }
            return $location;
        }

        // 方案二：cURL 备选
        $ch = curl_init();
        curl_setopt($ch, CURLOPT_URL, $url);
        curl_setopt($ch, CURLOPT_USERAGENT, $this->userAgent);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
        curl_setopt($ch, CURLOPT_HTTPGET, true);
        curl_setopt($ch, CURLOPT_MAXREDIRS, 10);
        curl_setopt($ch, CURLOPT_TIMEOUT, 10);
        curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);
        curl_setopt($ch, CURLOPT_SSL_VERIFYHOST, false);

        curl_exec($ch);
        $realUrl = curl_getinfo($ch, CURLINFO_EFFECTIVE_URL);
        curl_close($ch);

        return $realUrl ?: $url;
    }

    /**
     * 提取ID
     */
    private function extractId($url)
    {
        // 匹配 URL 中的数字 ID (通常是 video/xxx 或 modal_id=xxx)
        if (preg_match('/\/video\/(\d+)/', $url, $matches)) {
            return $matches[1];
        }
        if (preg_match('/\/share\/video\/(\d+)/', $url, $matches)) {
            return $matches[1];
        }
        if (preg_match('/modal_id=(\d+)/', $url, $matches)) {
            return $matches[1];
        }
        if (preg_match('/note\/(\d+)/', $url, $matches)) {
            return $matches[1];
        }
        // 尝试匹配纯数字 (防止某些短链解开后直接是ID)
        if (preg_match('/^(\d+)$/', $url, $matches)) {
            return $matches[1];
        }
        // 匹配 share/slides/xxx (新增)
        if (preg_match('/\/share\/slides\/(\d+)/', $url, $matches)) {
            return $matches[1];
        }
        // 匹配 share/video/xxx (新增)
        if (preg_match('/\/share\/video\/(\d+)/', $url, $matches)) {
            return $matches[1];
        }
        // 尝试匹配纯数字 (防止某些短链解开后直接是ID)
        return null;
    }

    /**
     * 主解析方法
     */
    public function parse($url)
    {
        if (empty($url)) {
            return $this->output(400, '请输入抖音链接');
        }

        // 预处理域名
        $domain = parse_url($url, PHP_URL_HOST);
        // 如果是短链接域名或不包含 video/modal_id 等特征，尝试获取重定向链接
        if ($domain == 'v.douyin.com' || strpos($url, 'douyin.com') === false || !$this->extractId($url)) {
            $url = $this->getRealUrl($url);
        }

        $id = $this->extractId($url);
        if (!$id) {
            return $this->output(400, '链接格式错误，无法提取ID。处理后的链接: ' . $url);
        }

        // 先请求作品详情接口。旧版本使用 user/self?modal_id，这个页面在
        // 当前抖音 Web 端通常只返回壳页面，无法提取作品数据。
        $apiUrl = 'https://www.douyin.com/aweme/v1/web/aweme/detail/?' . http_build_query([
            'device_platform' => 'webapp',
            'aid' => '6383',
            'channel' => 'channel_pc_web',
            'aweme_id' => $id,
            'pc_client_type' => '1',
            'version_code' => '190500',
            'version_name' => '19.5.0',
        ]);
        $apiResponse = $this->request($apiUrl, ['Accept: application/json, text/plain, */*', 'Referer: https://www.douyin.com/']);
        if ($apiResponse) {
            $apiData = json_decode($apiResponse, true);
            $detail = $apiData['aweme_detail'] ?? ($apiData['data']['aweme_detail'] ?? null);
            if (is_array($detail)) {
                return $this->formatData($detail);
            }
        }

        // 兼容旧版 iesdouyin 作品接口。当前 Web 详情接口被风控时，
        // 这个接口对部分公开作品仍会直接返回 item_list。
        $legacyUrl = 'https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids=' . urlencode($id);
        $legacyResponse = $this->request($legacyUrl, [
            'Accept: application/json, text/plain, */*',
            'Referer: https://www.iesdouyin.com/share/video/' . $id . '/',
        ]);
        if ($legacyResponse) {
            $legacyData = json_decode($legacyResponse, true);
            $legacyDetail = $legacyData['item_list'][0] ?? null;
            if (is_array($legacyDetail)) {
                return $this->formatData($legacyDetail);
            }
        }

        // 接口被风控时，回退到作品页面，而不是旧的 user/self 页面。
        $pageUrl = 'https://www.douyin.com/video/' . $id;
        $response = $this->request($pageUrl, ['Referer: https://www.douyin.com/']);
        if (!$response) {
            return $this->output(500, '请求失败');
        }

        $data = $this->extractJson($response);
        if ($data) {
            return $this->formatData($data);
        }

        return $this->output(404, '解析失败，未找到有效内容');
    }

    /**
     * 提取并解析 JSON 数据
     */
    private function extractJson($html)
    {
        $startStr = '<script id="RENDER_DATA" type="application/json">';
        $endStr = '</script>';

        $posStart = strpos($html, $startStr);
        if ($posStart === false) {
            // 尝试另一种模式 (douyin.php 中的模式)
            $pattern = '/window\._ROUTER_DATA\s*=\s*(.*?)\<\/script>/s';
            if (preg_match($pattern, $html, $matches)) {
                $json = json_decode(rtrim(trim($matches[1]), ';'), true);
                if (isset($json['loaderData'])) {
                    // 需要根据 loaderData 结构提取 videoDetail
                    // 这里的 key 可能是动态的，如 video_(id)/page
                    foreach ($json['loaderData'] as $key => $value) {
                        if (strpos($key, 'video_') === 0 && isset($value['videoInfoRes']['item_list'][0])) {
                            return $value['videoInfoRes']['item_list'][0];
                        }
                    }
                }
                $found = $this->findDetail($json);
                if (is_array($found)) {
                    return $found;
                }
            }
            return null;
        }

        $jsonStr = substr($html, $posStart + strlen($startStr));
        $posEnd = strpos($jsonStr, $endStr);
        if ($posEnd === false) {
            return null;
        }

        $jsonStr = substr($jsonStr, 0, $posEnd);
        $jsonStr = html_entity_decode(urldecode($jsonStr), ENT_QUOTES | ENT_HTML5, 'UTF-8');
        $data = json_decode($jsonStr, true);

        if (isset($data['app']['videoDetail'])) {
            return $data['app']['videoDetail'];
        }

        return $this->findDetail($data);
    }

    /** 从不同版本的页面 JSON 中递归寻找作品详情。 */
    private function findDetail($value)
    {
        if (!is_array($value)) {
            return null;
        }
        if (isset($value['aweme_detail']) && is_array($value['aweme_detail'])) {
            return $value['aweme_detail'];
        }
        if (isset($value['videoInfoRes']['item_list'][0]) && is_array($value['videoInfoRes']['item_list'][0])) {
            return $value['videoInfoRes']['item_list'][0];
        }
        if (isset($value['item_list'][0]) && is_array($value['item_list'][0])) {
            return $value['item_list'][0];
        }
        foreach ($value as $child) {
            $found = $this->findDetail($child);
            if (is_array($found)) {
                return $found;
            }
        }
        return null;
    }

    /**
     * 格式化数据 (统一为小红书格式)
     */
    private function formatData($detail)
    {
        $result = [
            'type' => 'unknown',
            'title' => $detail['desc'] ?? '',
            'desc' => $detail['desc'] ?? '',
            'author' => [
                'name' => $detail['authorInfo']['nickname'] ?? ($detail['author']['nickname'] ?? ''),
                'id' => $detail['authorInfo']['uid'] ?? ($detail['author']['uid'] ?? ''),
                'avatar' => $detail['authorInfo']['avatarUri'] ?? ($detail['author']['avatar_thumb']['url_list'][0] ?? ''),
            ],
            'cover' => '',
            'url' => null, // 视频链接
            'duration' => $detail['video']['duration'] ?? null,
            'video_backup' => null,
            'images' => [],
            'live_photo' => [],
            'music' => [
                'title' => $detail['music']['musicName'] ?? ($detail['music']['title'] ?? ''),
                'author' => $detail['music']['ownerNickname'] ?? ($detail['music']['author'] ?? ''),
                'url' => $detail['music']['playUrl']['uri'] ?? ($detail['music']['play_url']['uri'] ?? ''),
                'cover' => $detail['music']['coverThumb']['urlList'][0] ?? ($detail['music']['cover_thumb']['url_list'][0] ?? '')
            ]
        ];

        // 提取封面 (尝试多种字段)
        $cover = '';
        // 1. 尝试 originCover (原图封面)
        if (isset($detail['video']['originCover']['urlList'][0])) {
            $cover = $detail['video']['originCover']['urlList'][0];
        } elseif (isset($detail['video']['origin_cover']['url_list'][0])) {
            $cover = $detail['video']['origin_cover']['url_list'][0];
        } elseif (isset($detail['video']['originCover'])) {
            $cover = $detail['video']['originCover'];
        } elseif (isset($detail['video']['originCoverUrlList'][0])) {
            $cover = $detail['video']['originCoverUrlList'][0];
        }

        // 2. 尝试 cover (普通封面)
        if (!$cover) {
            // 某些情况下结构可能是 cover.url_list，也可能是 cover.urlList
            $cover = $detail['video']['cover']['urlList'][0] ?? ($detail['video']['cover']['url_list'][0] ?? '');

            // 如果 cover 是字符串 (直接是 URL)
            if (!$cover && isset($detail['video']['cover']) && is_string($detail['video']['cover'])) {
                $cover = $detail['video']['cover'];
            }
        }

        // 补充：检查是否直接在 detail.cover 字段 (某些图文类型)
        if (!$cover && isset($detail['cover']['url_list'][0])) {
            $cover = $detail['cover']['url_list'][0];
        }

        // 3. 尝试 dynamicCover (动态封面)
        if (!$cover) {
            $cover = $detail['video']['dynamicCover']['urlList'][0] ?? ($detail['video']['dynamic_cover']['url_list'][0] ?? '');
        }

        // 4. 尝试 douyin.php 中的路径逻辑 (针对 loaderData/videoInfoRes 结构)
        if (!$cover && isset($detail['videoInfoRes']['item_list'][0]['video']['cover']['url_list'][0])) {
            $cover = $detail['videoInfoRes']['item_list'][0]['video']['cover']['url_list'][0];
        }

        $result['cover'] = $cover;

        // 判断类型和提取资源
        $images = $detail['images'] ?? ($detail['image_post_info']['images'] ?? []);
        if (!empty($images)) {
            // 图文/图集/实况
            $result['type'] = 'image';

            foreach ($images as $img) {
                // 提取图片 URL
                $imgUrl = $img['urlList'][0] ?? ($img['url_list'][0] ?? ($img['download_url_list'][0] ?? ''));
                if ($imgUrl) {
                    $result['images'][] = $imgUrl;
                }

                // 提取实况视频 (Live Photo)
                // 抖音实况通常在 images 列表的 item 中包含 video 字段 (与普通图文不同)
                $liveVideoUrl = null;
                $videoInfo = $img['video'] ?? ($img['live_photo_video'] ?? []);

                // 1. 尝试 playAddr (对象数组结构，如 dylive.json)
                if (isset($videoInfo['playAddr']) && is_array($videoInfo['playAddr'])) {
                    $liveVideoUrl = null;
                    $v26Candidate = null;
                    // 优先匹配包含 v3-web 的链接
                    foreach ($videoInfo['playAddr'] as $addr) {
                        if (isset($addr['src'])) {
                            if (strpos($addr['src'], 'v3-web') !== false) {
                                $liveVideoUrl = $addr['src'];
                                break;
                            }
                            if (strpos($addr['src'], 'v26-web') !== false) {
                                $v26Candidate = $addr['src'];
                            }
                        }
                    }

                    if (!$liveVideoUrl && $v26Candidate) {
                        $liveVideoUrl = preg_replace('/:\/\/([^\/]+)/', '://v26-luna.douyinvod.com', $v26Candidate);
                    }

                    // 没找到 v3-web，则回退到备用逻辑 (优先取第二个，没有则第一个)
                    if (!$liveVideoUrl) {
                        $liveVideoUrl = $videoInfo['playAddr'][1]['src'] ?? ($videoInfo['playAddr'][0]['src'] ?? null);
                    }
                }

                // 2. 尝试 play_addr.url_list (字符串数组结构)
                if (!$liveVideoUrl && isset($videoInfo['play_addr']['url_list'])) {
                    $urlList = $videoInfo['play_addr']['url_list'];
                    $v26Candidate = null;
                    // 优先匹配包含 v3-web 的链接
                    foreach ($urlList as $url) {
                        if (strpos($url, 'v3-web') !== false) {
                            $liveVideoUrl = $url;
                            break;
                        }
                        if (strpos($url, 'v26-web') !== false) {
                            $v26Candidate = $url;
                        }
                    }

                    if (!$liveVideoUrl && $v26Candidate) {
                        $liveVideoUrl = preg_replace('/:\/\/([^\/]+)/', '://v26-luna.douyinvod.com', $v26Candidate);
                    }

                    // 没找到 v3-web，则回退到备用逻辑
                    if (!$liveVideoUrl) {
                        $liveVideoUrl = $urlList[1] ?? ($urlList[0] ?? null);
                    }
                }

                // 3. 尝试 playApi
                if (!$liveVideoUrl) {
                    $liveVideoUrl = $videoInfo['playApi'] ?? null;
                }

                if ($liveVideoUrl) {
                    $liveVideoUrl = str_replace('playwm', 'play', $liveVideoUrl);
                    $result['live_photo'][] = [
                        'image' => $imgUrl,
                        'video' => $liveVideoUrl
                    ];
                }
            }

            // 如果提取到了实况视频，修正类型为实况
            if (!empty($result['live_photo'])) {
                $result['type'] = 'live';
            }
        } else {
            // 视频
            $result['type'] = 'video';

            // 使用新逻辑提取最高画质视频
            $videoInfo = $this->extractHighestQualityVideo($detail);
            $result['url'] = $videoInfo['url'];
            $result['video_backup'] = $videoInfo['backup'];
            $result['video_id'] = $detail['video']['uri'] ?? '';
        }

        return $this->output(200, '解析成功', $result);
    }

    /**
     * 提取最高画质视频链接
     */
    private function extractHighestQualityVideo($detail)
    {
        $url = null;
        $backup = [];

        // 尝试从 bitRateList 中提取
        $bitRateList = $detail['video']['bitRateList'] ?? ($detail['video']['bit_rate'] ?? []);
        if (is_array($bitRateList)) {

            // 按 bitRate 降序排序
            usort($bitRateList, function ($a, $b) {
                return ($b['bitRate'] ?? ($b['bit_rate'] ?? 0)) - ($a['bitRate'] ?? ($a['bit_rate'] ?? 0));
            });

            // 遍历寻找合适的链接
            foreach ($bitRateList as $rateItem) {
                $playAddr = $rateItem['playAddr'][0]['src'] ?? ($rateItem['play_addr']['url_list'][0] ?? null);
                if ($playAddr) {
                    // 检查是否包含 v3-web 域名 (通常更稳定)
                    // 如果 playAddr 是数组，尝试找到 v3-web 的链接
                    $candidates = [];
                    if (isset($rateItem['playAddr']) && is_array($rateItem['playAddr'])) {
                        foreach ($rateItem['playAddr'] as $pa) {
                            if (isset($pa['src'])) $candidates[] = $pa['src'];
                        }
                    } elseif (isset($rateItem['play_addr']['url_list'])) {
                        $candidates = $rateItem['play_addr']['url_list'];
                    }

                    if (empty($candidates)) continue;

                    // 1. 在当前画质中选择最佳 URL
                    $currentBestUrl = null;
                    $v3Link = null;
                    $v26Link = null;

                    foreach ($candidates as $candidate) {
                        if (strpos($candidate, 'v3-web') !== false) {
                            $v3Link = $candidate;
                            break; // 找到 v3 优先使用
                        }
                        if (strpos($candidate, 'v26-web') !== false) {
                            $v26Link = $candidate;
                        }
                    }

                    if ($v3Link) {
                        $currentBestUrl = $v3Link;
                    } elseif ($v26Link) {
                        $currentBestUrl = preg_replace('/:\/\/([^\/]+)/', '://v26-luna.douyinvod.com', $v26Link);
                    } else {
                        $currentBestUrl = $candidates[0];
                    }

                    // 2. 如果全局 URL 尚未设置，使用当前最佳
                    if (!$url) {
                        $url = $currentBestUrl;
                    }

                    // 3. 将所有非主 URL 的链接加入备用
                    foreach ($candidates as $candidate) {
                        // 如果是 v26 链接，也进行域名替换，保持一致性
                        if (strpos($candidate, 'v26-web') !== false) {
                            $candidate = preg_replace('/:\/\/([^\/]+)/', '://v26-luna.douyinvod.com', $candidate);
                        }

                        // 排除已选用的主 URL
                        if ($candidate !== $url && !in_array($candidate, $backup)) {
                            $backup[] = $candidate;
                        }
                    }
                }

                if ($url && !empty($backup)) break; // 找到主备链接后停止
            }
        }

        // 如果 bitRateList 没找到，尝试旧逻辑
        if (!$url) {
            $uri = $detail['video']['uri'] ?? '';
            $playApi = $detail['video']['playApi'] ?? ($detail['video']['play_addr']['url_list'][0] ?? '');

            if ($playApi) {
                $url = str_replace('playwm', 'play', $playApi);
            } elseif ($uri) {
                $url = 'https://aweme.snssdk.com/aweme/v1/play/?video_id=' . $uri . '&ratio=720p&line=0';
            }

            // 备用
            $urlList = $detail['video']['play_addr']['url_list'] ?? [];
            if (count($urlList) > 1) {
                foreach ($urlList as $index => $link) {
                    if ($index === 0) continue;
                    $backup[] = str_replace('playwm', 'play', $link);
                }
            }
        }

        return ['url' => $url, 'backup' => $backup];
    }
}
