using UnityEngine;
using System.Collections.Generic;

/// <summary>
/// WeaponManager - 武器管理器
/// 管理玩家的所有武器、武器切换和弹药补给
/// </summary>
public class WeaponManager : MonoBehaviour
{
    [Header("武器列表")]
    [SerializeField] private List<WeaponBase> weapons = new List<WeaponBase>();
    
    [Header("当前武器")]
    [SerializeField] private int currentWeaponIndex = 0;
    
    [Header("切换设置")]
    [SerializeField] private float switchTime = 0.3f; // 武器切换时间
    
    private WeaponBase currentWeapon;
    private bool isSwitching = false;
    
    private void Start()
    {
        // 获取所有武器组件
        weapons = GetComponentsInChildren<WeaponBase>().ToList();
        
        if (weapons.Count > 0)
        {
            currentWeapon = weapons[0];
            EnableWeapon(currentWeapon);
        }
        else
        {
            Debug.LogWarning("没有找到任何武器！");
        }
    }
    
    /// <summary>
    /// 切换武器
    /// </summary>
    public void SwitchWeapon(int weaponIndex)
    {
        if (isSwitching || weaponIndex < 0 || weaponIndex >= weapons.Count)
        {
            return;
        }
        
        isSwitching = true;
        currentWeaponIndex = weaponIndex;
        
        StartCoroutine(SwitchWeaponCoroutine(weapons[weaponIndex]));
    }
    
    /// <summary>
    /// 切换到下一个武器
    /// </summary>
    public void NextWeapon()
    {
        int nextIndex = (currentWeaponIndex + 1) % weapons.Count;
        SwitchWeapon(nextIndex);
    }
    
    /// <summary>
    /// 切换到上一个武器
    /// </summary>
    public void PreviousWeapon()
    {
        int prevIndex = (currentWeaponIndex - 1 + weapons.Count) % weapons.Count;
        SwitchWeapon(prevIndex);
    }
    
    /// <summary>
    /// 武器切换协程
    /// </summary>
    private System.Collections.IEnumerator SwitchWeaponCoroutine(WeaponBase newWeapon)
    {
        // 禁用当前武器
        if (currentWeapon != null)
        {
            DisableWeapon(currentWeapon);
        }
        
        // 等待切换动画时间
        yield return new WaitForSeconds(switchTime);
        
        // 启用新武器
        currentWeapon = newWeapon;
        EnableWeapon(currentWeapon);
        
        isSwitching = false;
        Debug.Log($"切换到武器：{currentWeapon.GetWeaponName()}");
    }
    
    /// <summary>
    /// 启用武器
    /// </summary>
    private void EnableWeapon(WeaponBase weapon)
    {
        weapon.gameObject.SetActive(true);
    }
    
    /// <summary>
    /// 禁用武器
    /// </summary>
    private void DisableWeapon(WeaponBase weapon)
    {
        weapon.gameObject.SetActive(false);
    }
    
    /// <summary>
    /// 射击
    /// </summary>
    public void Fire()
    {
        if (currentWeapon != null && !isSwitching)
        {
            currentWeapon.Fire();
        }
    }
    
    /// <summary>
    /// 重新装填
    /// </summary>
    public void Reload()
    {
        if (currentWeapon != null && !isSwitching)
        {
            currentWeapon.Reload();
        }
    }
    
    /// <summary>
    /// 为当前武器添加弹药
    /// </summary>
    public void AddAmmo(int amount)
    {
        if (currentWeapon != null)
        {
            currentWeapon.AddReserveAmmo(amount);
            Debug.Log($"添加弹药：{amount}，当前备用弹药：{currentWeapon.GetReserveAmmo()}");
        }
    }
    
    /// <summary>
    /// 获取当前武器
    /// </summary>
    public WeaponBase GetCurrentWeapon()
    {
        return currentWeapon;
    }
    
    /// <summary>
    /// 获取武器数量
    /// </summary>
    public int GetWeaponCount()
    {
        return weapons.Count;
    }
    
    /// <summary>
    /// 获取当前武器索引
    /// </summary>
    public int GetCurrentWeaponIndex()
    {
        return currentWeaponIndex;
    }
    
    /// <summary>
    /// 检查是否正在切换武器
    /// </summary>
    public bool IsSwitching()
    {
        return isSwitching;
    }
}
