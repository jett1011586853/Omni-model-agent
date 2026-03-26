using UnityEngine;

/// <summary>
/// Deagle - 沙鹰手枪实现
/// 特点：高伤害、低射速、适合 ECO 局或补枪
/// </summary>
public class Deagle : WeaponBase
{
    [Header("Deagle 特殊属性")]
    [SerializeField] private float deagleDamage = 45f; // 手枪中最高伤害
    [SerializeField] private float deagleFireRate = 4f; // 射速很慢
    [SerializeField] private int deagleMagazineSize = 7; // 弹匣很小
    [SerializeField] private int deagleReserveAmmo = 35;
    
    [Header("爆头加成设置")]
    [SerializeField] private float headshotMultiplier = 3f; // 爆头伤害倍率更高
    
    [Header("后坐力设置")]
    [SerializeField] private float recoilMagnitude = 0.15f; // 单次后坐力大
    
    private void Start()
    {
        base.Start();
        weaponName = "Desert Eagle";
        damage = deagleDamage;
        fireRate = deagleFireRate;
        magazineSize = deagleMagazineSize;
        reserveAmmo = deagleReserveAmmo;
        currentMagazineAmmo = deagleMagazineSize;
    }
    
    /// <summary>
    /// 重写射击方法
    /// </summary>
    public override void Fire()
    {
        if (isReloading) return;
        
        float timeSinceLastFire = Time.time - lastFireTime;
        if (timeSinceLastFire < 1f / fireRate) return;
        
        if (currentMagazineAmmo <= 0)
        {
            PlaySound(emptySound);
            return;
        }
        
        lastFireTime = Time.time;
        currentMagazineAmmo--;
        isFiring = true;
        
        ApplyDeagleRecoil();
        PlaySound(fireSound);
        
        // 触发射线检测
        RaycastFireWithHeadshot();
        
        if (currentMagazineAmmo == 0)
        {
            isFiring = false;
        }
    }
    
    /// <summary>
    /// Deagle 后坐力应用（单次后坐力大）
    /// </summary>
    private void ApplyDeagleRecoil()
    {
        // Deagle 每次射击后坐力都很大
        currentRecoilY += recoilMagnitude;
        
        // 后坐力快速衰减
        currentRecoilY *= 0.8f;
    }
    
    /// <summary>
    /// 带爆头检测的射线射击
    /// </summary>
    protected void RaycastFireWithHeadshot()
    {
        Vector3 adjustedDirection = weaponTransform.forward;
        adjustedDirection.y += currentRecoilY;
        adjustedDirection.Normalize();
        
        Ray ray = new Ray(weaponTransform.position, adjustedDirection);
        
        if (Physics.Raycast(ray, out RaycastHit hit, 100f))
        {
            Debug.Log($"Deagle 击中：{hit.collider.name}");
            
            PlayerHealth targetHealth = hit.collider.GetComponent<PlayerHealth>();
            if (targetHealth != null)
            {
                bool isHeadshot = hit.collider.CompareTag("Head");
                float actualDamage = damage;
                
                if (isHeadshot)
                {
                    actualDamage *= headshotMultiplier;
                    Debug.Log("爆头！伤害加成");
                }
                
                targetHealth.TakeDamage((int)actualDamage);
            }
            
            CreateHitEffect(hit.point);
        }
    }
    
    /// <summary>
    /// 重写重新装填
    /// </summary>
    public override void Reload()
    {
        if (isReloading || currentMagazineAmmo == magazineSize || reserveAmmo <= 0)
        {
            return;
        }
        
        isReloading = true;
        PlaySound(reloadSound);
        
        // 沙鹰装填时间较长
        StartCoroutine(ReloadCoroutineWithDelay(3.5f));
    }
    
    /// <summary>
    /// 带延迟的重新装填协程
    /// </summary>
    protected System.Collections.IEnumerator ReloadCoroutineWithDelay(float delay)
    {
        yield return new WaitForSeconds(delay);
        
        int ammoNeeded = magazineSize - currentMagazineAmmo;
        int ammoToLoad = Mathf.Min(ammoNeeded, reserveAmmo);
        
        currentMagazineAmmo += ammoToLoad;
        reserveAmmo -= ammoToLoad;
        
        isReloading = false;
        Debug.Log($"Deagle 重新装填完成：{currentMagazineAmmo}/{magazineSize}");
    }
}
