"""
费用计算器测试脚本 — 验证真实费用计算的正确性
"""
import sys
sys.path.insert(0, '.')

from back.cost_calculator import CostCalculator

def test_cost_calculation():
    """测试费用计算"""
    print("=" * 60)
    print("费用计算器测试")
    print("=" * 60)
    
    # 初始化计算器
    calc = CostCalculator()
    
    # 测试场景1：美国市场 - FOB - 40HQ - 2箱
    print("\n【场景1】美国市场 FOB 40HQ 2箱")
    print("-" * 60)
    input_data = {
        "destCountry": "美国",
        "volume": 136,  # 2个40HQ
        "weight": 24000,  # 12吨/箱
        "boxCount": 2,
    }
    result = calc.calculate(
        input_data=input_data,
        factory_name="山东英科医疗制品有限公司",
        origin_port="青岛/QINGDAO",
        dest_port="洛杉矶/LOS ANGELES",
        trade_term="FOB",
        box_type="40HQ"
    )
    
    print(f"使用箱数: {result['box_count']}")
    print(f"总费用: ¥{result['total_cny']:,.2f} (${result['total_usd']:,.2f})")
    print(f"\n费用明细:")
    for item in result['items']:
        print(f"  {item['name']}: ¥{item['amount_cny']:,.2f} ({item['basis']})")
    
    print(f"\n计算详情:")
    for detail in result['calc_details']:
        print(f"  {detail}")
    
    # 测试场景2：欧洲市场 - CIF - 40HQ - 1箱
    print("\n\n【场景2】德国市场 CIF 40HQ 1箱")
    print("-" * 60)
    input_data2 = {
        "destCountry": "德国",
        "volume": 68,
        "weight": 12000,
        "boxCount": 1,
    }
    result2 = calc.calculate(
        input_data=input_data2,
        factory_name="安徽英科医疗用品有限公司",
        origin_port="上海/SHANGHAI",
        dest_port="汉堡/HAMBURG",
        trade_term="CIF",
        box_type="40HQ"
    )
    
    print(f"使用箱数: {result2['box_count']}")
    print(f"总费用: ¥{result2['total_cny']:,.2f} (${result2['total_usd']:,.2f})")
    print(f"\n费用明细:")
    for item in result2['items']:
        print(f"  {item['name']}: ¥{item['amount_cny']:,.2f} ({item['basis']})")
    
    # 测试场景3：东南亚市场 - FOB - 20GP - 1箱
    print("\n\n【场景3】新加坡市场 FOB 20GP 1箱")
    print("-" * 60)
    input_data3 = {
        "destCountry": "新加坡",
        "volume": 25,
        "weight": 8000,
        "boxCount": 1,
    }
    result3 = calc.calculate(
        input_data=input_data3,
        factory_name="江西英科医疗有限公司",
        origin_port="上海/SHANGHAI",
        dest_port="新加坡/SINGAPORE",
        trade_term="FOB",
        box_type="20GP"
    )
    
    print(f"使用箱数: {result3['box_count']}")
    print(f"总费用: ¥{result3['total_cny']:,.2f} (${result3['total_usd']:,.2f})")
    print(f"\n费用明细:")
    for item in result3['items']:
        print(f"  {item['name']}: ¥{item['amount_cny']:,.2f} ({item['basis']})")
    
    # 测试场景4：DDP条款（包含目的港费用）
    print("\n\n【场景4】英国市场 DDP 40HQ 1箱")
    print("-" * 60)
    input_data4 = {
        "destCountry": "英国",
        "volume": 70,
        "weight": 13000,
        "boxCount": 1,
    }
    result4 = calc.calculate(
        input_data=input_data4,
        factory_name="安庆英科医疗有限公司",
        origin_port="上海/SHANGHAI",
        dest_port="伦敦/LONDON",
        trade_term="DDP",
        box_type="40HQ"
    )
    
    print(f"使用箱数: {result4['box_count']}")
    print(f"总费用: ¥{result4['total_cny']:,.2f} (${result4['total_usd']:,.2f})")
    print(f"\n费用明细:")
    for item in result4['items']:
        print(f"  {item['name']}: ¥{item['amount_cny']:,.2f} ({item['basis']})")
    
    # 对比分析
    print("\n\n" + "=" * 60)
    print("【对比分析】")
    print("=" * 60)
    print(f"{'场景':<20} {'箱型':<8} {'箱数':<6} {'总费用(CNY)':<15} {'总费用(USD)':<12}")
    print("-" * 60)
    print(f"{'美国 FOB':<20} {'40HQ':<8} {result['box_count']:<6} {result['total_cny']:<15,.2f} {result['total_usd']:<12,.2f}")
    print(f"{'德国 CIF':<20} {'40HQ':<8} {result2['box_count']:<6} {result2['total_cny']:<15,.2f} {result2['total_usd']:<12,.2f}")
    print(f"{'新加坡 FOB':<20} {'20GP':<8} {result3['box_count']:<6} {result3['total_cny']:<15,.2f} {result3['total_usd']:<12,.2f}")
    print(f"{'英国 DDP':<20} {'40HQ':<8} {result4['box_count']:<6} {result4['total_cny']:<15,.2f} {result4['total_usd']:<12,.2f}")
    
    print("\n✅ 测试完成！")
    print("💡 费用说明：")
    print("  1. 港杂费：按箱数计算，青岛2800/箱，上海2500/箱")
    print("  2. VGM费：5元/箱")
    print("  3. 舱单费：55元/单（固定）")
    print("  4. 陆运费：根据工厂→港口距离×箱数计算")
    print("  5. 报关费：330-380元/单（按港口）")
    print("  6. 海运费：根据航线×箱型×距离计算（CIF/CFR/DDP/DAP条款）")
    print("  7. 保险费：海运费×0.3%（仅CIF）")
    print("  8. 目的港费用：始发港杂费×80%（仅DDP/DAP）")

if __name__ == "__main__":
    test_cost_calculation()