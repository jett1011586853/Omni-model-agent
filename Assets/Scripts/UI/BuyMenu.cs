using UnityEngine;
using System.Collections.Generic;

/// <summary>
/// BuyMenu - 购买菜单
/// 管理回合开始时的购买阶段，允许玩家购买武器、护甲和道具
/// </summary>
public class BuyMenu : MonoBehaviour
{
    [Header("购买设置")]
    [SerializeField] private float buyPhaseDuration = 15f;
    [SerializeField] private float buyMenuDelay = 2f; // 回合开始后延迟打开购买菜单
    
    [Header("引用")]
    [SerializeField] private EconomySystem economySystem;
    [SerializeField] private RoundManager roundManager;
    [SerializeField] private WeaponManager weaponManager;
    
    // 物品价格表
    [System.Serializable]
    public class ItemPrice
    {
        public string itemName;
        public int price;
        public ItemCategory category;
    }
    
    public List<ItemPrice> itemPrices = new List<ItemPrice>();
    
    // 购买阶段状态
    public bool isBuyPhaseActive { get; private set; }
    public float buyPhaseTimeRemaining { get; private set; }
    
    // 事件
    public delegate void BuyPhaseEventHandler();
    public event BuyPhaseEventHandler OnBuyPhaseStart;
    public event BuyPhaseEventHandler OnBuyPhaseEnd;
    
    private void Start()
    {
        if (economySystem == null)
        {
            economySystem = FindObjectOfType<EconomySystem>();
        }
        
        if (roundManager == null)
        {
            roundManager = FindObjectOfType<RoundManager>();
        }
        
        // 订阅回合事件
        if (roundManager != null)
        {
            roundManager.OnRoundStart += HandleRoundStart;
            roundManager.OnBuyPhaseEnd += HandleBuyPhaseEnd;
        }
        
        InitializeItemPrices();
    }
    
    /// <summary>
    /// 初始化物品价格
    /// </summary>
    private void InitializeItemPrices()
    {
        // 武器价格
        itemPrices.Add(new ItemPrice { itemName = "Glock-18", price = 200, category = ItemCategory.Pistol });
        itemPrices.Add(new ItemPrice { itemName = "Deagle", price = 700, category = ItemCategory.Pistol });
        itemPrices.Add(new ItemPrice { itemName = "AK-47", price = 2700, category = ItemCategory.Rifle });
        itemPrices.Add(new ItemPrice { itemName = "M4A4", price = 3100, category = ItemCategory.Rifle });
        itemPrices.Add(new ItemPrice { itemName = "M4A1-S", price = 2900, category = ItemCategory.Rifle });
        
        // 护甲价格
        itemPrices.Add(new ItemPrice { itemName = "Helmet", price = 350, category = ItemCategory.Armor });
        itemPrices.Add(new ItemPrice { itemName = "Kevlar Vest", price = 650, category = ItemCategory.Armor });
        itemPrices.Add(new ItemPrice { itemName = "Kevlar + Helmet", price = 1000, category = ItemCategory.Armor });
        
        // 道具价格
        itemPrices.Add(new ItemPrice { itemName = "Flashbang", price = 200, category = ItemCategory.Grenade });
        itemPrices.Add(new ItemPrice { itemName = "HE Grenade", price = 300, category = ItemCategory.Grenade });
        itemPrices.Add(new ItemPrice { itemName = "Smoke Grenade", price = 400, category = ItemCategory.Grenade });
        itemPrices.Add(new ItemPrice { itemName = "Molotov", price = 300, category = ItemCategory.Grenade });
    }
    
    /// <summary>
    /// 处理回合开始
    /// </summary>
    private void HandleRoundStart()
    {
        StartCoroutine(BuyPhaseCoroutine());
    }
    
    /// <summary>
    /// 购买阶段协程
    /// </summary>
    private System.Collections.IEnumerator BuyPhaseCoroutine()
    {
        // 延迟打开购买菜单
        yield return new WaitForSeconds(buyMenuDelay);
        
        isBuyPhaseActive = true;
        buyPhaseTimeRemaining = buyPhaseDuration;
        
        Debug.Log("购买菜单已打开！");
        OnBuyPhaseStart?.Invoke();
        
        // 购买倒计时
        while (buyPhaseTimeRemaining > 0 && isBuyPhaseActive)
        {
            buyPhaseTimeRemaining -= Time.deltaTime;
            yield return null;
        }
        
        CloseBuyMenu();
    }
    
    /// <summary>
    /// 处理购买阶段结束
    /// </summary>
    private void HandleBuyPhaseEnd()
    {
        CloseBuyMenu();
    }
    
    /// <summary>
    /// 关闭购买菜单
    /// </summary>
    private void CloseBuyMenu()
    {
        isBuyPhaseActive = false;
        buyPhaseTimeRemaining = 0;
        
        Debug.Log("购买菜单已关闭");
        OnBuyPhaseEnd?.Invoke();
    }
    
    /// <summary>
    /// 玩家尝试购买物品
    /// </summary>
    /// <param name="playerId">玩家 ID</param>
    /// <param name="itemName">物品名称</param>
    /// <returns>是否购买成功</returns>
    public bool TryBuyItem(int playerId, string itemName)
    {
        if (!isBuyPhaseActive)
        {
            Debug.Log($"玩家 {playerId} 无法购买：购买阶段已结束");
            return false;
        }
        
        // 查找物品价格
        ItemPrice item = itemPrices.Find(p => p.itemName == itemName);
        if (item == null)
        {
            Debug.Log($"物品 {itemName} 不存在");
            return false;
        }
        
        // 尝试购买
        if (economySystem != null && economySystem.TryBuyItem(playerId, item.price))
        {
            Debug.Log($"玩家 {playerId} 成功购买 {itemName}，花费 ${item.price}");
            
            // 根据物品类型执行不同逻辑
            switch (item.category)
            {
                case ItemCategory.Pistol:
                    OnPistolPurchased(playerId, itemName);
                    break;
                case ItemCategory.Rifle:
                    OnRiflePurchased(playerId, itemName);
                    break;
                case ItemCategory.Armor:
                    OnArmorPurchased(playerId, itemName);
                    break;
                case ItemCategory.Grenade:
                    OnGrenadePurchased(playerId, itemName);
                    break;
            }
            
            return true;
        }
        
        return false;
    }
    
    /// <summary>
    /// 手枪购买处理
    /// </summary>
    private void OnPistolPurchased(int playerId, string pistolName)
    {
        if (weaponManager != null)
        {
            weaponManager.EquipWeapon(playerId, pistolName);
        }
    }
    
    /// <summary>
    /// 步枪购买处理
    /// </summary>
    private void OnRiflePurchased(int playerId, string rifleName)
    {
        if (weaponManager != null)
        {
            weaponManager.EquipWeapon(playerId, rifleName);
        }
    }
    
    /// <summary>
    /// 护甲购买处理
    /// </summary>
    private void OnArmorPurchased(int playerId, string armorName)
    {
        // TODO: 更新玩家护甲值
        Debug.Log($"玩家 {playerId} 装备护甲：{armorName}");
    }
    
    /// <summary>
    /// 道具购买处理
    /// </summary>
    private void OnGrenadePurchased(int playerId, string grenadeName)
    {
        // TODO: 添加道具到玩家背包
        Debug.Log($"玩家 {playerId} 购买道具：{grenadeName}");
    }
    
    /// <summary>
    /// 获取物品价格
    /// </summary>
    public int GetItemPrice(string itemName)
    {
        ItemPrice item = itemPrices.Find(p => p.itemName == itemName);
        return item != null ? item.price : 0;
    }
    
    /// <summary>
    /// 获取所有可用物品
    /// </summary>
    public List<string> GetAvailableItems()
    {
        List<string> items = new List<string>();
        foreach (var item in itemPrices)
        {
            items.Add(item.itemName);
        }
        return items;
    }
    
    private void OnDisable()
    {
        if (roundManager != null)
        {
            roundManager.OnRoundStart -= HandleRoundStart;
            roundManager.OnBuyPhaseEnd -= HandleBuyPhaseEnd;
        }
    }
}

/// <summary>
/// 物品分类
/// </summary>
public enum ItemCategory
{
    Pistol,     // 手枪
    Rifle,      // 步枪
    Armor,      // 护甲
    Grenade     // 道具
}
