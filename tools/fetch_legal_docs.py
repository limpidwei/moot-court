"""
法律文档获取脚本

从权威来源下载法律文档并保存为 Markdown 格式

使用方法：
    python tools/fetch_legal_docs.py [--domain civil] [--doc-id minfadian]

示例：
    python tools/fetch_legal_docs.py --domain civil  # 下载所有民法文档
    python tools/fetch_legal_docs.py --doc-id minfadian  # 只下载民法典
"""

import sys
import argparse
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.rag.config import CIVIL_LAW_DOCUMENTS, LEGAL_KNOWLEDGE_DIR


def fetch_document(doc_config: dict, domain: str = "civil") -> bool:
    """
    获取单个法律文档

    Args:
        doc_config: 文档配置
        domain: 法律领域

    Returns:
        是否成功
    """
    doc_id = doc_config["id"]
    doc_name = doc_config["name"]
    filename = doc_config["filename"]

    print(f"\n正在获取: {doc_name}")
    print(f"文档ID: {doc_id}")

    # 创建目标目录
    target_dir = LEGAL_KNOWLEDGE_DIR / domain
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename

    # 如果文件已存在，跳过
    if target_path.exists():
        print(f"✓ 文档已存在: {target_path}")
        return True

    # 根据文档ID确定来源URL
    source_urls = get_source_urls()
    if doc_id not in source_urls:
        print(f"⚠ 未配置来源URL: {doc_id}")
        return False

    url = source_urls[doc_id]
    print(f"来源: {url}")

    # 使用 WebFetch 获取内容
    try:
        from backend.rag.web_fetcher import fetch_and_parse_url
        content = fetch_and_parse_url(url)

        if not content:
            print(f"✗ 获取内容失败")
            return False

        # 保存为 Markdown
        markdown_content = convert_to_markdown(content, doc_config)
        target_path.write_text(markdown_content, encoding="utf-8")

        print(f"✓ 已保存: {target_path}")
        print(f"  大小: {len(markdown_content)} 字符")
        return True

    except Exception as e:
        print(f"✗ 获取失败: {e}")
        return False


def get_source_urls() -> dict:
    """
    获取所有文档的来源URL映射

    Returns:
        {doc_id: url} 映射
    """
    return {
        "minfadian": "https://flk.npc.gov.cn/detail2.html?MmM5MDlmZGQ2NzlhZjJlNjAxNjc5YmY5ZTc2NTAxNGY%3D",
        "minfadian_shijianxiaoli": "https://www.court.gov.cn/fabu/xiangqing/283771.html",
        "minfadian_zongze": "https://www.court.gov.cn/fabu/xiangqing/346931.html",
        "minfadian_wuquan": "https://www.court.gov.cn/fabu/xiangqing/283791.html",
        "minfadian_hetong": "https://www.court.gov.cn/fabu/xiangqing/417921.html",
        "minfadian_danbao": "https://www.court.gov.cn/fabu/xiangqing/283801.html",
        "minfadian_hunyin1": "https://www.court.gov.cn/fabu/xiangqing/283781.html",
        "minfadian_hunyin2": "https://www.court.gov.cn/fabu/xiangqing/452771.html",
        "minfadian_jicheng": "https://www.court.gov.cn/fabu/xiangqing/283811.html",
        "minfadian_qinquan": "https://www.court.gov.cn/fabu/xiangqing/443891.html",
        "minjian_jiedai": "https://www.court.gov.cn/fabu/xiangqing/249031.html",
        "maimai_hetong": "https://www.court.gov.cn/fabu/xiangqing/283821.html",
        "shangpinfang_maimai": "https://www.court.gov.cn/fabu/xiangqing/283831.html",
        "jianshe_gongcheng": "https://www.court.gov.cn/fabu/xiangqing/283841.html",
        "laodong_zhengyi1": "https://www.court.gov.cn/fabu/xiangqing/283851.html",
        "laodong_zhengyi2": "https://www.court.gov.cn/fabu/xiangqing/472691.html",
    }


def convert_to_markdown(html_content: str, doc_config: dict) -> str:
    """
    将 HTML 内容转换为 Markdown

    Args:
        html_content: HTML 内容
        doc_config: 文档配置

    Returns:
        Markdown 格式的内容
    """
    # 添加文档头
    header = f"""# {doc_config['name']}

**文档编号**: {doc_config.get('doc_number', 'N/A')}
**生效日期**: {doc_config.get('effective_date', 'N/A')}
**文档类型**: {doc_config.get('type', 'N/A')}

---

"""

    # 简单的 HTML 到 Markdown 转换
    # 实际使用中可能需要更复杂的转换逻辑
    markdown = html_content

    # 替换常见的 HTML 标签
    import re
    markdown = re.sub(r'<h1[^>]*>(.*?)</h1>', r'# \1\n', markdown)
    markdown = re.sub(r'<h2[^>]*>(.*?)</h2>', r'## \1\n', markdown)
    markdown = re.sub(r'<h3[^>]*>(.*?)</h3>', r'### \1\n', markdown)
    markdown = re.sub(r'<p[^>]*>(.*?)</p>', r'\1\n\n', markdown, flags=re.DOTALL)
    markdown = re.sub(r'<br\s*/?>', '\n', markdown)
    markdown = re.sub(r'<[^>]+>', '', markdown)  # 移除剩余 HTML 标签

    # 清理多余空行
    markdown = re.sub(r'\n{3,}', '\n\n', markdown)

    return header + markdown.strip()


def main():
    parser = argparse.ArgumentParser(description="获取法律文档")
    parser.add_argument("--domain", default="civil", help="法律领域 (default: civil)")
    parser.add_argument("--doc-id", help="只获取指定文档")
    args = parser.parse_args()

    # 根据 domain 选择文档清单
    if args.domain == "civil":
        documents = CIVIL_LAW_DOCUMENTS
    else:
        print(f"未支持的领域: {args.domain}")
        sys.exit(1)

    # 过滤文档
    if args.doc_id:
        documents = [d for d in documents if d["id"] == args.doc_id]
        if not documents:
            print(f"未找到文档: {args.doc_id}")
            sys.exit(1)

    print(f"准备获取 {len(documents)} 个文档...")

    # 获取文档
    success_count = 0
    fail_count = 0

    for doc_config in documents:
        if fetch_document(doc_config, args.domain):
            success_count += 1
        else:
            fail_count += 1

    print(f"\n{'='*60}")
    print(f"获取完成:")
    print(f"  成功: {success_count}")
    print(f"  失败: {fail_count}")
    print(f"  总计: {len(documents)}")


if __name__ == "__main__":
    main()
