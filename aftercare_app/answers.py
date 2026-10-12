"""7.2：保守的FAQ摘录基线。只接受已定义问法，不冒充语义推理。"""
import re

FAQ = {
    '商品破损怎么办': 'product-damage',
    '收到商品损坏如何处理': 'product-damage',
    '配送超时怎么办': 'delivery-delay',
    '怎么咨询退货换货': 'return-query',
    '在哪里查看工单进度': 'ticket-progress',
    '工单关闭就是退款了吗': 'ticket-progress',
    '谁能关闭工单': 'ticket-close',
    '可以查看别人的订单吗': 'privacy',
}


def normalize(text):
    return re.sub(r'[\s？?。！!，,]', '', text)


def answer(index, query):
    candidates = index.search(query)
    source_id = FAQ.get(normalize(query))
    citation = next((c for c in candidates if c['id'] == source_id), None)
    result = {'mode': 'faq-extractive-v1', 'generated_answer': False,
              'corpus_sha256': index.digest, 'citations': [], 'related': candidates}
    if citation:
        result.update(status='quoted', answer=citation['text'], citations=[citation])
    else:
        result.update(status='abstained', answer='当前基线不能可靠回答这个问法。下面如有相关条款，仅供核对；具体订单请查看本人订单，资料未规定的事项请提交工单咨询。')
    return result
