"""
法律文档下载脚本

从官方权威来源下载法律文档并保存为 Markdown 格式。
请在本地运行此脚本（WebFetch 工具无法访问政府域名）。

使用方法：
    pip install requests beautifulsoup4
    python tools/download_legal_docs.py

或下载单个文档：
    python tools/download_legal_docs.py --doc minfadian
"""

import os
import re
import sys
import argparse
import json
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("请先安装依赖: pip install requests beautifulsoup4")
    sys.exit(1)


# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
LEGAL_KNOWLEDGE_DIR = PROJECT_ROOT / "data" / "legal_knowledge" / "civil"


# HTTP 请求配置
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def clean_html_to_markdown(html_content: str) -> str:
    """
    将 HTML 内容转换为 Markdown 格式

    Args:
        html_content: HTML 字符串

    Returns:
        Markdown 格式的文本
    """
    soup = BeautifulSoup(html_content, "html.parser")

    # 移除 script 和 style 标签
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    # 获取文本内容
    text = soup.get_text(separator="\n")

    # 清理多余空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    # 识别条款编号并格式化
    # 匹配 "第X条" 格式
    text = re.sub(
        r"第([一二三四五六七八九十百千零\d]+)条\s*",
        r"\n\n**第\1条** ",
        text,
    )

    # 匹配 "第X章" 格式
    text = re.sub(
        r"第([一二三四五六七八九十百千零\d]+)章\s*",
        r"\n\n## 第\1章 ",
        text,
    )

    # 匹配 "第X编" 格式
    text = re.sub(
        r"第([一二三四五六七八九十百千零\d]+)编\s*",
        r"\n\n# 第\1编 ",
        text,
    )

    return text


def download_from_url(url: str, timeout: int = 30) -> str | None:
    """
    从 URL 下载内容

    Args:
        url: 目标 URL
        timeout: 超时时间（秒）

    Returns:
        下载的 HTML 内容，失败返回 None
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout)
        response.encoding = response.apparent_encoding or "utf-8"

        if response.status_code == 200:
            return response.text
        else:
            print(f"  HTTP {response.status_code}")
            return None
    except Exception as e:
        print(f"  下载失败: {e}")
        return None


def fetch_minfadian() -> str | None:
    """获取民法典全文"""
    # 来源：最高人民检察院
    url = "https://www.spp.gov.cn/spp/fl/202006/t20200602_463888.shtml"

    print(f"  Source: {url}")
    html = download_from_url(url)

    if html:
        return clean_html_to_markdown(html)
    return None


def fetch_minfadian_shijianxiaoli() -> str | None:
    """获取民法典时间效力规定"""
    url = "https://www.court.gov.cn/fabu/xiangqing/282051.html"

    print(f"  Source: {url}")
    html = download_from_url(url)

    if html:
        return clean_html_to_markdown(html)
    return None


def fetch_minfadian_zongze() -> str | None:
    """获取民法典总则编解释"""
    url = "https://www.court.gov.cn/fabu/xiangqing/347221.html"

    print(f"  Source: {url}")
    html = download_from_url(url)

    if html:
        return clean_html_to_markdown(html)
    return None


def fetch_minfadian_wuquan() -> str | None:
    """获取民法典物权编解释（一）"""
    url = "https://www.court.gov.cn/fabu/xiangqing/282101.html"

    print(f"  Source: {url}")
    html = download_from_url(url)

    if html:
        return clean_html_to_markdown(html)
    return None


def fetch_minfadian_hetong() -> str | None:
    """获取民法典合同编通则解释"""
    url = "https://www.court.gov.cn/fabu/xiangqing/419382.html"

    print(f"  Source: {url}")
    html = download_from_url(url)

    if html:
        return clean_html_to_markdown(html)
    return None


def fetch_minfadian_danbao() -> str | None:
    """获取民法典担保制度解释"""
    url = "https://www.court.gov.cn/fabu/xiangqing/282721.html"

    print(f"  Source: {url}")
    html = download_from_url(url)

    if html:
        return clean_html_to_markdown(html)
    return None


def fetch_minfadian_hunyin1() -> str | None:
    """获取民法典婚姻家庭编解释（一）"""
    url = "https://www.court.gov.cn/fabu/xiangqing/282071.html"

    print(f"  Source: {url}")
    html = download_from_url(url)

    if html:
        return clean_html_to_markdown(html)
    return None


def fetch_minfadian_hunyin2() -> str | None:
    """获取民法典婚姻家庭编解释（二）"""
    url = "https://www.court.gov.cn/zixun/xiangqing/452771.html"

    print(f"  Source: {url}")
    html = download_from_url(url)

    if html:
        return clean_html_to_markdown(html)
    return None


def fetch_minfadian_jicheng() -> str | None:
    """获取民法典继承编解释（一）"""
    url = "https://www.court.gov.cn/fabu/xiangqing/282091.html"

    print(f"  Source: {url}")
    html = download_from_url(url)

    if html:
        return clean_html_to_markdown(html)
    return None


def fetch_minfadian_qinquan() -> str | None:
    """获取民法典侵权责任编解释（一）"""
    url = "https://www.court.gov.cn/zixun/xiangqing/443891.html"

    print(f"  Source: {url}")
    html = download_from_url(url)

    if html:
        return clean_html_to_markdown(html)
    return None


def fetch_minjian_jiedai() -> str | None:
    """获取民间借贷司法解释"""
    url = "https://www.court.gov.cn/fabu/xiangqing/249031.html"

    print(f"  Source: {url}")
    html = download_from_url(url)

    if html:
        return clean_html_to_markdown(html)
    return None


def fetch_maimai_hetong() -> str | None:
    """获取买卖合同纠纷解释 (included in batch modification 法释〔2020〕18号)"""
    url = "https://www.court.gov.cn/fabu/xiangqing/282631.html"

    print(f"  Source: {url}")
    html = download_from_url(url)

    if html:
        return clean_html_to_markdown(html)
    return None


def fetch_shangpinfang_maimai() -> str | None:
    """获取商品房买卖合同纠纷解释 (included in batch modification 法释〔2020〕18号)"""
    url = "https://www.court.gov.cn/fabu/xiangqing/282631.html"

    print(f"  Source: {url}")
    html = download_from_url(url)

    if html:
        return clean_html_to_markdown(html)
    return None


def fetch_jianshe_gongcheng() -> str | None:
    """获取建设工程施工合同纠纷解释（一）"""
    url = "https://www.court.gov.cn/zixun/xiangqing/282111.html"

    print(f"  Source: {url}")
    html = download_from_url(url)

    if html:
        return clean_html_to_markdown(html)
    return None


def fetch_laodong_zhengyi1() -> str | None:
    """获取劳动争议司法解释（一）"""
    url = "https://www.court.gov.cn/fabu/xiangqing/282121.html"

    print(f"  Source: {url}")
    html = download_from_url(url)

    if html:
        return clean_html_to_markdown(html)
    return None


def fetch_laodong_zhengyi2() -> str | None:
    """获取劳动争议司法解释（二）"""
    url = "https://www.court.gov.cn/fabu/xiangqing/472691.html"

    print(f"  Source: {url}")
    html = download_from_url(url)

    if html:
        return clean_html_to_markdown(html)
    return None


# 文档配置
DOCUMENTS = {
    "minfadian": {
        "name": "中华人民共和国民法典",
        "filename": "01_民法典.md",
        "doc_number": "无",
        "publish_date": "2020-05-28",
        "effective_date": "2021-01-01",
        "type": "law",
        "fetch_func": fetch_minfadian,
    },
    "minfadian_shijianxiaoli": {
        "name": "最高人民法院关于适用《中华人民共和国民法典》时间效力的若干规定",
        "filename": "02_民法典时间效力规定.md",
        "doc_number": "法释〔2020〕15号",
        "publish_date": "2020-12-29",
        "effective_date": "2021-01-01",
        "type": "judicial_interpretation",
        "fetch_func": fetch_minfadian_shijianxiaoli,
    },
    "minfadian_zongze": {
        "name": "最高人民法院关于适用《中华人民共和国民法典》总则编若干问题的解释",
        "filename": "03_民法典总则编解释.md",
        "doc_number": "法释〔2022〕6号",
        "publish_date": "2022-03-01",
        "effective_date": "2022-03-01",
        "type": "judicial_interpretation",
        "fetch_func": fetch_minfadian_zongze,
    },
    "minfadian_wuquan": {
        "name": "最高人民法院关于适用《中华人民共和国民法典》物权编的解释（一）",
        "filename": "04_民法典物权编解释一.md",
        "doc_number": "法释〔2020〕24号",
        "publish_date": "2020-12-29",
        "effective_date": "2021-01-01",
        "type": "judicial_interpretation",
        "fetch_func": fetch_minfadian_wuquan,
    },
    "minfadian_hetong": {
        "name": "最高人民法院关于适用《中华人民共和国民法典》合同编通则若干问题的解释",
        "filename": "05_民法典合同编通则解释.md",
        "doc_number": "法释〔2023〕13号",
        "publish_date": "2023-12-05",
        "effective_date": "2023-12-05",
        "type": "judicial_interpretation",
        "fetch_func": fetch_minfadian_hetong,
    },
    "minfadian_danbao": {
        "name": "最高人民法院关于适用《中华人民共和国民法典》有关担保制度的解释",
        "filename": "06_民法典担保制度解释.md",
        "doc_number": "法释〔2020〕28号",
        "publish_date": "2020-12-29",
        "effective_date": "2021-01-01",
        "type": "judicial_interpretation",
        "fetch_func": fetch_minfadian_danbao,
    },
    "minfadian_hunyin1": {
        "name": "最高人民法院关于适用《中华人民共和国民法典》婚姻家庭编的解释（一）",
        "filename": "07_民法典婚姻家庭编解释一.md",
        "doc_number": "法释〔2020〕22号",
        "publish_date": "2020-12-29",
        "effective_date": "2021-01-01",
        "type": "judicial_interpretation",
        "fetch_func": fetch_minfadian_hunyin1,
    },
    "minfadian_hunyin2": {
        "name": "最高人民法院关于适用《中华人民共和国民法典》婚姻家庭编的解释（二）",
        "filename": "08_民法典婚姻家庭编解释二.md",
        "doc_number": "法释〔2025〕1号",
        "publish_date": "2025-01-15",
        "effective_date": "2025-02-01",
        "type": "judicial_interpretation",
        "fetch_func": fetch_minfadian_hunyin2,
    },
    "minfadian_jicheng": {
        "name": "最高人民法院关于适用《中华人民共和国民法典》继承编的解释（一）",
        "filename": "09_民法典继承编解释一.md",
        "doc_number": "法释〔2020〕23号",
        "publish_date": "2020-12-29",
        "effective_date": "2021-01-01",
        "type": "judicial_interpretation",
        "fetch_func": fetch_minfadian_jicheng,
    },
    "minfadian_qinquan": {
        "name": "最高人民法院关于适用《中华人民共和国民法典》侵权责任编的解释（一）",
        "filename": "10_民法典侵权责任编解释一.md",
        "doc_number": "法释〔2024〕12号",
        "publish_date": "2024-09-26",
        "effective_date": "2024-09-27",
        "type": "judicial_interpretation",
        "fetch_func": fetch_minfadian_qinquan,
    },
    "minjian_jiedai": {
        "name": "最高人民法院关于审理民间借贷案件适用法律若干问题的规定（2020第二次修正）",
        "filename": "11_民间借贷司法解释.md",
        "doc_number": "法释〔2020〕17号",
        "publish_date": "2020-12-29",
        "effective_date": "2021-01-01",
        "type": "judicial_interpretation",
        "fetch_func": fetch_minjian_jiedai,
    },
    "maimai_hetong": {
        "name": "最高人民法院关于审理买卖合同纠纷案件适用法律问题的解释（2020修正）",
        "filename": "12_买卖合同纠纷解释.md",
        "doc_number": "法释〔2020〕17号",
        "publish_date": "2020-12-29",
        "effective_date": "2021-01-01",
        "type": "judicial_interpretation",
        "fetch_func": fetch_maimai_hetong,
    },
    "shangpinfang_maimai": {
        "name": "最高人民法院关于审理商品房买卖合同纠纷案件适用法律若干问题的解释（2020修正）",
        "filename": "13_商品房买卖合同纠纷解释.md",
        "doc_number": "法释〔2020〕17号",
        "publish_date": "2020-12-29",
        "effective_date": "2021-01-01",
        "type": "judicial_interpretation",
        "fetch_func": fetch_shangpinfang_maimai,
    },
    "jianshe_gongcheng": {
        "name": "最高人民法院关于审理建设工程施工合同纠纷案件适用法律问题的解释（一）",
        "filename": "14_建设工程施工合同纠纷解释一.md",
        "doc_number": "法释〔2020〕25号",
        "publish_date": "2020-12-29",
        "effective_date": "2021-01-01",
        "type": "judicial_interpretation",
        "fetch_func": fetch_jianshe_gongcheng,
    },
    "laodong_zhengyi1": {
        "name": "最高人民法院关于审理劳动争议案件适用法律问题的解释（一）",
        "filename": "15_劳动争议司法解释一.md",
        "doc_number": "法释〔2020〕26号",
        "publish_date": "2020-12-29",
        "effective_date": "2021-01-01",
        "type": "judicial_interpretation",
        "fetch_func": fetch_laodong_zhengyi1,
    },
    "laodong_zhengyi2": {
        "name": "最高人民法院关于审理劳动争议案件适用法律问题的解释（二）",
        "filename": "16_劳动争议司法解释二.md",
        "doc_number": "法释〔2025〕12号",
        "publish_date": "2025-08-01",
        "effective_date": "2025-09-01",
        "type": "judicial_interpretation",
        "fetch_func": fetch_laodong_zhengyi2,
    },
}


def generate_markdown_header(doc_config: dict) -> str:
    """
    生成 Markdown 文档头部

    Args:
        doc_config: 文档配置

    Returns:
        Markdown 格式的头部
    """
    return f"""# {doc_config['name']}

**文号**: {doc_config['doc_number']}
**发布日期**: {doc_config['publish_date']}
**施行日期**: {doc_config['effective_date']}
**文档类型**: {doc_config['type']}

---

"""


def download_document(doc_id: str, force: bool = False) -> bool:
    """
    下载单个文档

    Args:
        doc_id: 文档 ID
        force: 是否强制覆盖已存在的文件

    Returns:
        是否成功
    """
    if doc_id not in DOCUMENTS:
        print(f"✗ 未知的文档 ID: {doc_id}")
        return False

    doc_config = DOCUMENTS[doc_id]
    output_path = LEGAL_KNOWLEDGE_DIR / doc_config["filename"]

    # 检查文件是否已存在
    if output_path.exists() and not force:
        print(f"[OK] Exists: {doc_config['filename']} (use --force to overwrite)")
        return True

    print(f"\nDownloading: {doc_config['name']}")
    print(f"  Doc Number: {doc_config['doc_number']}")

    # 调用对应的下载函数
    content = doc_config["fetch_func"]()

    if content:
        # 生成完整的 Markdown 文件
        markdown = generate_markdown_header(doc_config) + content

        # 保存到文件
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")

        print(f"  [OK] Saved: {output_path}")
        print(f"    Size: {len(markdown)} chars")
        return True
    else:
        print(f"  [FAIL] Download failed")
        return False


def download_all(force: bool = False) -> dict:
    """
    下载所有文档

    Args:
        force: 是否强制覆盖已存在的文件

    Returns:
        下载结果统计
    """
    results = {"success": 0, "failed": 0, "skipped": 0}

    for doc_id in DOCUMENTS:
        doc_config = DOCUMENTS[doc_id]
        output_path = LEGAL_KNOWLEDGE_DIR / doc_config["filename"]

        # 检查是否已存在
        if output_path.exists() and not force:
            print(f"✓ 已存在: {doc_config['filename']}")
            results["skipped"] += 1
            continue

        if download_document(doc_id, force):
            results["success"] += 1
        else:
            results["failed"] += 1

    return results


def verify_documents() -> dict:
    """
    验证已下载的文档

    Returns:
        验证结果
    """
    results = {"valid": [], "invalid": [], "missing": []}

    for doc_id, doc_config in DOCUMENTS.items():
        output_path = LEGAL_KNOWLEDGE_DIR / doc_config["filename"]

        if not output_path.exists():
            results["missing"].append(doc_id)
            continue

        content = output_path.read_text(encoding="utf-8")

        # 验证文档是否包含关键内容
        checks = []

        # 检查文号
        if doc_config["doc_number"] != "无":
            if doc_config["doc_number"] in content:
                checks.append(("文号", True))
            else:
                checks.append(("文号", False))

        # 检查条款编号（应该有"第X条"格式）
        if re.search(r"第[一二三四五六七八九十百千零\d]+条", content):
            checks.append(("条款编号", True))
        else:
            checks.append(("条款编号", False))

        # 检查文档长度（应该足够长）
        if len(content) > 1000:
            checks.append(("文档长度", True))
        else:
            checks.append(("文档长度", False))

        # 判断是否有效
        if all(check[1] for check in checks):
            results["valid"].append(doc_id)
        else:
            results["invalid"].append((doc_id, checks))

    return results


def main():
    parser = argparse.ArgumentParser(description="下载法律文档")
    parser.add_argument("--doc", help="下载指定文档（文档 ID）")
    parser.add_argument("--all", action="store_true", help="下载所有文档")
    parser.add_argument("--force", action="store_true", help="强制覆盖已存在的文件")
    parser.add_argument("--verify", action="store_true", help="验证已下载的文档")
    parser.add_argument("--list", action="store_true", help="列出所有文档 ID")
    args = parser.parse_args()

    if args.list:
        print("可用的文档 ID：")
        for doc_id, doc_config in DOCUMENTS.items():
            print(f"  {doc_id:30s} - {doc_config['name']}")
        return

    if args.verify:
        print("验证已下载的文档...")
        results = verify_documents()
        print(f"\n验证结果：")
        print(f"  有效: {len(results['valid'])}")
        print(f"  无效: {len(results['invalid'])}")
        print(f"  缺失: {len(results['missing'])}")

        if results["invalid"]:
            print("\n无效文档：")
            for doc_id, checks in results["invalid"]:
                print(f"  {doc_id}:")
                for check_name, passed in checks:
                    status = "✓" if passed else "✗"
                    print(f"    {status} {check_name}")

        if results["missing"]:
            print(f"\n缺失文档: {', '.join(results['missing'])}")
        return

    if args.doc:
        download_document(args.doc, args.force)
    elif args.all:
        results = download_all(args.force)
        print(f"\n下载完成：")
        print(f"  成功: {results['success']}")
        print(f"  失败: {results['failed']}")
        print(f"  跳过: {results['skipped']}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
