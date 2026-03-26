using UnityEngine;
using UnityEngine.UI;

/// <summary>
/// 弹药显示 - 显示当前武器的弹药信息
/// </summary>
public class AmmoHUD : MonoBehaviour
{
    [Header("UI 组件引用")]
    [Tooltip("当前弹药数文本")]
    public Text currentAmmoText;
    
    [Tooltip("总弹药数文本")]
    public Text totalAmmoText;
    
    [Tooltip("武器名称文本")]
    public Text weaponNameText;
    
    [Header("显示设置")]
    [Tooltip("是否显示武器名称")]
    public bool showWeaponName = true;
    
    [Tooltip("是否显示总弹药")]
    public bool showTotalAmmo = true;
    
    private string currentWeaponName = "无武器";
    private int currentAmmo = 0;
    private int totalAmmo = 0;
    
    private void Start()
    {
        UpdateDisplay();
    }
    
    /// <summary>
    /// 更新弹药显示
    /// </summary>
    public void UpdateAmmo(string weaponName, int current, int total)
    {
        currentWeaponName = weaponName;
        currentAmmo = current;
        totalAmmo = total;
        UpdateDisplay();
    }
    
    /// <summary>
    /// 仅更新当前弹药数（用于射击时）
    /// </summary>
    public void UpdateCurrentAmmo(int current)
    {
        currentAmmo = current;
        UpdateDisplay();
    }
    
    /// <summary>
    /// 更新总弹药数（用于换弹后）
    /// </summary>
    public void UpdateTotalAmmo(int total)
    {
        totalAmmo = total;
        UpdateDisplay();
    }
    
    private void UpdateDisplay()
    {
        if (currentAmmoText != null)
        {
            currentAmmoText.text = currentAmmo.ToString();
        }
        
        if (totalAmmoText != null && showTotalAmmo)
        {
            totalAmmoText.text = totalAmmo.ToString();
        }
        else if (totalAmmoText != null)
        {
            totalAmmoText.text = "";
        }
        
        if (weaponNameText != null && showWeaponName)
        {
            weaponNameText.text = currentWeaponName;
        }
        else if (weaponNameText != null)
        {
            weaponNameText.text = "";
        }
    }
    
    /// <summary>
    /// 设置弹药不足警告（可选）
    /// </summary>
    public void SetLowAmmoWarning(bool isLow)
    {
        if (currentAmmoText != null)
        {
            // 弹药少于 5 发时显示红色警告
            currentAmmoText.color = isLow ? Color.red : Color.white;
        }
    }
}
